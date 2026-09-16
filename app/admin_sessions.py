"""Password and opaque-session isolation for the standalone Admin Console."""

from datetime import datetime, timedelta, timezone
import hashlib
import secrets
from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import SecretStr
from sqlalchemy.orm import Session

from app import auth, models
from app.database import get_db


COOKIE_NAME = "rilono_admin_session"
COOKIE_PATH = "/api"
REQUIRED_HEADER = "X-Admin-Console-Session"
SESSION_SECONDS = max(60, auth.ACCESS_TOKEN_EXPIRE_MINUTES * 60)
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def sensitive_input(endpoint):
    endpoint.admin_sensitive_input = True
    return endpoint


class SensitiveInputRoute(APIRoute):
    """Do not echo password-bearing request inputs in validation errors."""

    def get_route_handler(self):
        handler = super().get_route_handler()
        if not getattr(self.endpoint, "admin_sensitive_input", False):
            return handler

        async def sanitized(request):
            try:
                return await handler(request)
            except RequestValidationError as error:
                details = [{key: item[key] for key in ("loc", "msg", "type") if key in item}
                           for item in error.errors()]
                return JSONResponse(status_code=422, content={"detail": details},
                                    headers={"Cache-Control": "no-store"})
        return sanitized


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def credential_for(db: Session, user_id: int):
    return (db.query(models.AdminConsoleCredential).populate_existing()
            .filter(models.AdminConsoleCredential.user_id == user_id).first())


def has_console_password(db: Session, user_id: int) -> bool:
    return credential_for(db, user_id) is not None


def prepare_password(password: SecretStr | None, email: str) -> str | None:
    if password is None:
        return None
    raw = password.get_secret_value()
    error = auth.validate_password_strength(raw, email)
    if error:
        # Validate explicitly so FastAPI never includes the raw password in a
        # Pydantic validation-error response's `input` field.
        raise HTTPException(400, error)
    return auth.get_password_hash(raw)


def delete_user_sessions(db: Session, user_id: int) -> None:
    db.query(models.AdminConsoleSession).filter_by(user_id=user_id).delete(synchronize_session=False)


def set_password_hash(db: Session, user_id: int, password_hash: str) -> None:
    row = credential_for(db, user_id)
    if row is None:
        db.add(models.AdminConsoleCredential(user_id=user_id, password_hash=password_hash))
    else:
        row.password_hash = password_hash
    delete_user_sessions(db, user_id)


def revoke_credentials(db: Session, user_id: int) -> None:
    delete_user_sessions(db, user_id)
    db.query(models.AdminConsoleCredential).filter_by(user_id=user_id).delete(synchronize_session=False)


def _fingerprint(user, source: str, credential=None) -> str:
    if source == "console" and credential is not None:
        value = "console:" + credential.password_hash
    elif source == "personal":
        invalidated = user.session_invalidated_at
        stamp = _utc(invalidated).isoformat() if invalidated else ""
        value = "personal:" + user.hashed_password + ":" + stamp
    else:
        return ""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _origin(value: str | None) -> tuple[str, str] | None:
    try:
        parsed = urlsplit(value or "")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
            return None
        return parsed.scheme.lower(), parsed.netloc.lower()
    except ValueError:
        return None


def require_same_origin(request: Request) -> None:
    # The console uses same-origin requests. Do not inherit the public site's
    # wider CORS/CSRF list: a sibling Enterprise host must not control this cookie.
    expected_scheme = "https" if auth._request_uses_https(request) else request.url.scheme
    expected = (expected_scheme.lower(), request.url.netloc.lower())
    supplied = request.headers.get("origin")
    if supplied is None:
        supplied = request.headers.get("referer")
    if _origin(supplied) != expected:
        raise HTTPException(403, "Cross-origin Admin Console request blocked.")


def set_session_cookie(request: Request, response: Response, token: str) -> None:
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=auth._resolve_auth_cookie_secure(request), samesite="strict", path=COOKIE_PATH)
    response.headers["Cache-Control"] = "no-store"


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path=COOKIE_PATH, httponly=True, samesite="strict")
    response.headers["Cache-Control"] = "no-store"


def create_session(db: Session, user, source: str, credential=None) -> str:
    now = datetime.now(timezone.utc)
    token = secrets.token_urlsafe(32)
    db.query(models.AdminConsoleSession).filter(
        models.AdminConsoleSession.user_id == user.id,
        models.AdminConsoleSession.expires_at <= now,
    ).delete(synchronize_session=False)
    db.add(models.AdminConsoleSession(token_hash=token_hash(token), user_id=user.id, auth_source=source,
                                     auth_fingerprint=_fingerprint(user, source, credential),
                                     expires_at=now + timedelta(seconds=SESSION_SECONDS)))
    return token


def session_user(db: Session, token: str):
    from app.admin_access import require_access

    invalid = HTTPException(401, "Admin Console session expired. Please sign in again.")
    if not token or len(token) > 256:
        raise invalid
    session = (db.query(models.AdminConsoleSession).populate_existing()
               .filter_by(token_hash=token_hash(token)).first())
    if session is None or _utc(session.expires_at) <= datetime.now(timezone.utc):
        raise invalid
    user = db.query(models.User).populate_existing().filter_by(id=session.user_id).first()
    if user is None:
        raise invalid
    require_access(db, user)
    credential = credential_for(db, user.id)
    # Creating a separate credential ends the main-password path, including old
    # personal-password-backed console sessions, even if a row escaped cleanup.
    if session.auth_source == "personal" and credential is not None:
        raise invalid
    expected = _fingerprint(user, session.auth_source, credential)
    if not expected or not secrets.compare_digest(expected, session.auth_fingerprint):
        raise invalid
    return user


def get_current_console_user(request: Request, response: Response,
                             db: Session = Depends(get_db),
                             token: str | None = Depends(auth.oauth2_scheme)):
    from app.admin_access import is_legacy_admin

    # A present but invalid console cookie never falls through to another account
    # in the shared personal cookie. Frontend requests require this isolated mode.
    if COOKIE_NAME in request.cookies:
        if request.method not in SAFE_METHODS:
            require_same_origin(request)
        return session_user(db, request.cookies.get(COOKIE_NAME) or "")
    if request.headers.get(REQUIRED_HEADER, "").lower() == "required":
        raise HTTPException(401, "Sign in to the Admin Console.")
    if request.method not in SAFE_METHODS and auth.AUTH_COOKIE_NAME in request.cookies:
        require_same_origin(request)
    user = auth.get_current_user(request, response, token, db)
    auth.get_current_active_user(user)
    if not is_legacy_admin(user) and has_console_password(db, user.id):
        raise HTTPException(401, "Use your separate Admin Console password to sign in.")
    return user
