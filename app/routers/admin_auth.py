"""Public login/logout for isolated Admin Console sessions."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, SecretStr
from sqlalchemy import func
from sqlalchemy.orm import Session

from app import admin_access, admin_sessions, auth, models
from app.database import get_db
from app.routers.admin import (
    _clear_admin_turnstile_cookie, _enforce_rate_limit_or_429,
    _is_admin_turnstile_required, verify_turnstile_token,
)
from app.utils.rate_limiter import extract_client_ip


router = APIRouter(prefix="/api/admin-auth", tags=["admin-auth"], route_class=admin_sessions.SensitiveInputRoute)


class ConsoleLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: EmailStr
    password: SecretStr
    cf_turnstile_token: str | None = None


@router.post("/login")
@admin_sessions.sensitive_input
def login(payload: ConsoleLogin, request: Request, response: Response, db: Session = Depends(get_db)):
    admin_sessions.require_same_origin(request)
    _enforce_rate_limit_or_429(request=request, scope="admin.console.login", limit=12,
                             window_seconds=300, extra_key=None)
    if _is_admin_turnstile_required(request):
        challenge = (payload.cf_turnstile_token or "").strip()
        if not challenge or not verify_turnstile_token(challenge, extract_client_ip(request)):
            raise HTTPException(400, "Security verification failed. Please try again.")
    invalid = HTTPException(401, "Incorrect email or password, or console access is unavailable.")
    raw = payload.password.get_secret_value()
    if not raw or len(raw.encode("utf-8")) > auth.PASSWORD_MAX_BYTES:
        raise invalid
    # Match Team mutations' lock order: User first, then credentials/membership.
    # Reset/revoke cannot commit between this authorization check and issuance.
    user = (db.query(models.User).populate_existing().with_for_update()
            .filter(func.lower(models.User.email) == str(payload.email).lower()).first())
    if user is None:
        raise invalid
    credential = admin_sessions.credential_for(db, user.id)
    stored_hash = credential.password_hash if credential is not None else user.hashed_password
    try:
        password_ok = auth.verify_password(raw, stored_hash)
    except (ValueError, TypeError):
        password_ok = False
    if not password_ok:
        raise invalid
    try:
        admin_access.require_access(db, user)
    except HTTPException:
        raise invalid
    source = "console" if credential is not None else "personal"
    token = admin_sessions.create_session(db, user, source, credential)
    db.commit()
    admin_sessions.set_session_cookie(request, response, token)
    _clear_admin_turnstile_cookie(response)
    return {"message": "Signed in to the Admin Console."}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    admin_sessions.require_same_origin(request)
    token = request.cookies.get(admin_sessions.COOKIE_NAME) or ""
    if token and len(token) <= 256:
        db.query(models.AdminConsoleSession).filter_by(token_hash=admin_sessions.token_hash(token)).delete(synchronize_session=False)
        db.commit()
    admin_sessions.clear_session_cookie(response)
    _clear_admin_turnstile_cookie(response)
    return {"message": "Signed out of the Admin Console."}
