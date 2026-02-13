from datetime import datetime, timedelta
from typing import Optional
import re
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.database import get_db
from app import models, schemas
import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise RuntimeError("SECRET_KEY environment variable must be set.")
if SECRET_KEY == "your-secret-key-change-in-production":
    raise RuntimeError("Insecure SECRET_KEY detected. Set a strong unique SECRET_KEY.")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "30"))
PASSWORD_MIN_LENGTH = int(os.getenv("PASSWORD_MIN_LENGTH", "10"))
PASSWORD_MAX_BYTES = int(os.getenv("PASSWORD_MAX_BYTES", "200"))
COMMON_WEAK_PASSWORDS = {
    "password",
    "password123",
    "123456",
    "12345678",
    "qwerty",
    "qwerty123",
    "admin",
    "admin123",
    "letmein",
    "welcome",
    "iloveyou",
    "abc123",
}

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
AUTH_COOKIE_NAME = os.getenv("AUTH_COOKIE_NAME", "rilono_access_token").strip() or "rilono_access_token"

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="api/auth/login", auto_error=False)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    # Handle passwords longer than 72 bytes by hashing first
    # This ensures compatibility with bcrypt's 72-byte limit
    import hashlib
    password_bytes = plain_password.encode('utf-8')
    
    # For passwords longer than 72 bytes, hash with SHA256 first
    if len(password_bytes) > 72:
        password_hash = hashlib.sha256(password_bytes).hexdigest()
        return pwd_context.verify(password_hash, hashed_password)
    
    # For passwords <= 72 bytes, verify directly
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password: str) -> str:
    # Bcrypt has a 72-byte limit, so we hash longer passwords with SHA256 first
    import hashlib
    password_bytes = password.encode('utf-8')
    if len(password_bytes) > 72:
        # Hash with SHA256 first to get a fixed-length 64-char hex string
        password = hashlib.sha256(password_bytes).hexdigest()
    return pwd_context.hash(password)


def validate_password_strength(password: str, user_email: Optional[str] = None) -> Optional[str]:
    """Return an error message when password is weak; otherwise return None."""
    if not password:
        return "Password is required."

    errors: list[str] = []
    password_bytes = password.encode("utf-8")
    password_lower = password.lower()

    if len(password) < PASSWORD_MIN_LENGTH:
        errors.append(f"at least {PASSWORD_MIN_LENGTH} characters")
    if len(password_bytes) > PASSWORD_MAX_BYTES:
        errors.append(f"at most {PASSWORD_MAX_BYTES} bytes")
    if any(ch.isspace() for ch in password):
        errors.append("no spaces")
    if not re.search(r"[a-z]", password):
        errors.append("one lowercase letter")
    if not re.search(r"[A-Z]", password):
        errors.append("one uppercase letter")
    if not re.search(r"\d", password):
        errors.append("one number")
    if not re.search(r"[^A-Za-z0-9]", password):
        errors.append("one special character")
    if password_lower in COMMON_WEAK_PASSWORDS:
        errors.append("not a common password")

    if user_email:
        email_local = user_email.split("@")[0].lower().strip()
        if len(email_local) >= 3 and email_local in password_lower:
            errors.append("must not contain your email username")

    if errors:
        return "Password must include " + ", ".join(errors) + "."
    return None

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def authenticate_user(db: Session, email: str, password: str):
    # Authenticate using email address
    user = db.query(models.User).filter(models.User.email == email).first()
    if not user:
        return False
    if not verify_password(password, user.hashed_password):
        return False
    return user

def _decode_token_subject(token: str) -> Optional[str]:
    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    email: str = payload.get("sub")
    if email is None:
        return None
    return email


def get_current_user(
    request: Request,
    token: Optional[str] = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    cookie_token = (request.cookies.get(AUTH_COOKIE_NAME) or "").strip()
    header_token = (token or "").strip()

    # For browser sessions, prefer secure HttpOnly cookie over Authorization header.
    candidate_token = cookie_token or header_token
    if not candidate_token:
        raise credentials_exception

    decoded_email: Optional[str] = None
    try:
        decoded_email = _decode_token_subject(candidate_token)
    except JWTError:
        raise credentials_exception

    email = (decoded_email or "").strip()
    if not email:
        raise credentials_exception

    # Look up user by email (backward compatible: also check username for old tokens)
    user = db.query(models.User).filter(models.User.email == email).first()
    if user is None:
        # Fallback for old tokens that might have username
        user = db.query(models.User).filter(models.User.username == email).first()
    if user is None:
        raise credentials_exception
    return user

def get_current_active_user(current_user: models.User = Depends(get_current_user)):
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

def get_current_admin_user(current_user: models.User = Depends(get_current_active_user)):
    """Require admin or developer access"""
    if not (current_user.is_admin or current_user.is_developer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin or developer access required"
        )
    return current_user
