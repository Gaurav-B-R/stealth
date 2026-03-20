import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
from pydantic import BaseModel, EmailStr

from app.database import get_db, SessionLocal
from app import models
from app.auth import (
    authenticate_user,
    create_access_token,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    set_auth_cookie,
)
from app.utils.rate_limiter import extract_client_ip, is_request_ip_whitelisted
from app.utils.turnstile import is_turnstile_enabled, verify_turnstile_token

router = APIRouter(prefix="/api/enterprise", tags=["enterprise"])


class EnterpriseLoginRequest(BaseModel):
    email: EmailStr
    password: str
    cf_turnstile_token: Optional[str] = None


def _is_development_env() -> bool:
    return os.getenv("ENVIRONMENT", "production").strip().lower() == "development"


def _is_turnstile_required() -> bool:
    return is_turnstile_enabled() and not _is_development_env()


def seed_enterprise_user() -> None:
    """
    Sync enterprise credential rows from PostgreSQL into users table for auth/session reuse.
    """
    db = SessionLocal()
    try:
        credentials = (
            db.query(models.EnterpriseCredential)
            .filter(models.EnterpriseCredential.is_active.is_(True))
            .all()
        )
        if not credentials:
            return

        changes_made = False
        for entry in credentials:
            email = (entry.email or "").strip().lower()
            password_hash = (entry.password_hash or "").strip()
            if not email or not password_hash:
                continue

            existing = db.query(models.User).filter(models.User.email == email).first()
            if existing:
                existing.hashed_password = password_hash
                existing.is_active = True
                existing.email_verified = True
                existing.is_admin = True
                if not existing.full_name:
                    existing.full_name = (entry.full_name or "Enterprise Admin").strip()
                if not existing.university:
                    existing.university = "Enterprise Account"
                if existing.accepted_terms_privacy_at is None:
                    existing.accepted_terms_privacy_at = datetime.utcnow()
                changes_made = True
                continue

            user = models.User(
                email=email,
                username=None,
                hashed_password=password_hash,
                full_name=(entry.full_name or "Enterprise Admin").strip(),
                university="Enterprise Account",
                is_active=True,
                email_verified=True,
                is_admin=True,
                accepted_terms_privacy_at=datetime.utcnow(),
            )
            db.add(user)
            changes_made = True

        if changes_made:
            db.commit()
    finally:
        db.close()


@router.post("/login")
async def enterprise_login(
    payload: EnterpriseLoginRequest,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    turnstile_token = (payload.cf_turnstile_token or "").strip()
    ip_whitelisted = is_request_ip_whitelisted(request)
    if is_turnstile_enabled() and not ip_whitelisted:
        if turnstile_token:
            client_ip = extract_client_ip(request) if request else None
            if not verify_turnstile_token(turnstile_token, client_ip):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Security verification failed. Please try again.",
                )
        elif _is_turnstile_required():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Security verification is required",
            )

    user = authenticate_user(db, payload.email.lower().strip(), payload.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not (user.is_admin or user.is_developer):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Enterprise access is restricted.",
        )

    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account is deactivated.")

    user.last_login_at = datetime.utcnow()
    db.commit()

    access_token = create_access_token(
        data={"sub": user.email},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES),
    )
    set_auth_cookie(request, response, access_token)

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "is_admin": user.is_admin,
        },
    }
