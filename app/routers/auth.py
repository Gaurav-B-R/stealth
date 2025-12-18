from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta
from app.database import get_db
from app import models, schemas
from app.auth import (
    authenticate_user,
    create_access_token,
    get_password_hash,
    get_current_active_user,
    ACCESS_TOKEN_EXPIRE_MINUTES
)

router = APIRouter(prefix="/api/auth", tags=["authentication"])

def extract_email_domain(email: str) -> str:
    """Extract domain from email address."""
    if '@' not in email:
        return ""
    return email.split('@')[1].lower()

@router.get("/university-by-email", response_model=schemas.UniversityInfo)
def get_university_by_email(email: str, db: Session = Depends(get_db)):
    """Get university information based on email domain."""
    email_domain = extract_email_domain(email)
    if not email_domain:
        raise HTTPException(status_code=400, detail="Invalid email format")
    
    university = db.query(models.USUniversity).filter(
        models.USUniversity.email_domain == email_domain
    ).first()
    
    if not university:
        return {"university_name": None, "email_domain": email_domain, "is_valid": False}
    
    return {
        "university_name": university.university_name,
        "email_domain": university.email_domain,
        "is_valid": True
    }

@router.post("/register", response_model=schemas.UserResponse, status_code=status.HTTP_201_CREATED)
def register(user: schemas.UserCreate, db: Session = Depends(get_db)):
    # Extract email domain
    email_domain = extract_email_domain(user.email)
    
    if not email_domain:
        raise HTTPException(status_code=400, detail="Invalid email format")
    
    # Validate email domain against us_universities table
    university = db.query(models.USUniversity).filter(
        models.USUniversity.email_domain == email_domain
    ).first()
    
    if not university:
        raise HTTPException(
            status_code=403,
            detail="Registration is restricted to students with valid university email addresses. Please use your university email domain."
        )
    
    # Check if user already exists
    db_user = db.query(models.User).filter(models.User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    
    # Auto-generate username from email if not provided
    username = user.username
    if not username:
        # Use email as username (or extract part before @)
        username = user.email.split('@')[0]
    
    # Check if auto-generated username already exists (unlikely but possible)
    db_user = db.query(models.User).filter(models.User.username == username).first()
    if db_user:
        # If username exists, append a number
        counter = 1
        while db.query(models.User).filter(models.User.username == f"{username}{counter}").first():
            counter += 1
        username = f"{username}{counter}"
    
    # Validate password length
    if len(user.password.encode('utf-8')) > 200:
        raise HTTPException(status_code=400, detail="Password is too long. Maximum 200 characters allowed.")
    
    # Create new user with auto-filled university name
    try:
        hashed_password = get_password_hash(user.password)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"Password hashing error: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail="An error occurred during registration. Please try again.")
    
    # Auto-fill university name from the database (ignore user-provided university)
    db_user = models.User(
        email=user.email,
        username=username,  # Auto-generated from email
        hashed_password=hashed_password,
        full_name=user.full_name,
        university=university.university_name,  # Auto-filled from database
        phone=user.phone
    )
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@router.post("/login", response_model=schemas.Token)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # OAuth2PasswordRequestForm uses "username" field, but we treat it as email
    user = authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    # Additional validation: Check if user's email domain is still valid
    email_domain = extract_email_domain(user.email)
    if email_domain:
        university = db.query(models.USUniversity).filter(
            models.USUniversity.email_domain == email_domain
        ).first()
        if not university:
            raise HTTPException(
                status_code=403,
                detail="Your account email domain is no longer valid. Please contact support."
            )
    
    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    # Store email in token instead of username
    access_token = create_access_token(
        data={"sub": user.email}, expires_delta=access_token_expires
    )
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=schemas.UserResponse)
def read_users_me(current_user: models.User = Depends(get_current_active_user)):
    return current_user

