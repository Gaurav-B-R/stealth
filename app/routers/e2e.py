"""
End-to-end encryption (E2E) key-vault endpoints.

The browser owns all the cryptography (see static/e2e_crypto.js): it generates a random
master key and wraps it with a key derived from the user's *encryption passphrase* (which
is NEVER sent to the server) and with a one-time *recovery code*. This router only stores
and returns those OPAQUE wrapped blobs plus the public KDF parameters. The server has no
path to the passphrase, the recovery code, or the unwrapped master key — that is what makes
the "not even we can read your documents" claim true.

Endpoints:
  POST /api/e2e/setup             first-time vault creation (rejects if already set up)
  GET  /api/e2e/vault             fetch wrapped blobs + KDF params for in-browser unlock
  POST /api/e2e/rotate-passphrase replace the passphrase wrap (browser re-wraps with old passphrase)
  POST /api/e2e/recover           replace the passphrase wrap after unlocking via recovery code
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app import models
from app.auth import get_current_active_user
from app.utils.rate_limiter import check_ip_rate_limit

router = APIRouter(prefix="/api/e2e", tags=["e2e"])
logger = logging.getLogger(__name__)

# Wrapped key material is small (a 32-byte key + AES-GCM IV/tag, base64). Cap generously to
# reject abuse without rejecting legitimate blobs.
MAX_BLOB_CHARS = 4096
MAX_KDF_CHARS = 512

E2E_WRITE_RATE_LIMIT = int(os.getenv("E2E_WRITE_RATE_LIMIT", "12"))
E2E_WRITE_RATE_WINDOW_SECONDS = int(os.getenv("E2E_WRITE_RATE_WINDOW_SECONDS", "900"))
E2E_READ_RATE_LIMIT = int(os.getenv("E2E_READ_RATE_LIMIT", "60"))
E2E_READ_RATE_WINDOW_SECONDS = int(os.getenv("E2E_READ_RATE_WINDOW_SECONDS", "300"))


def _enforce_rate_limit_or_429(request: Request, scope: str, limit: int, window_seconds: int) -> None:
    allowed, retry_after = check_ip_rate_limit(
        request=request, scope=scope, limit=limit, window_seconds=window_seconds
    )
    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )


def _validate_blob(value: str, field: str) -> str:
    value = (value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail=f"{field} is required.")
    if len(value) > MAX_BLOB_CHARS:
        raise HTTPException(status_code=400, detail=f"{field} is too large.")
    try:
        base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=400, detail=f"{field} must be valid base64.")
    return value


def _validate_kdf(value: str) -> str:
    value = (value or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="kdf is required.")
    if len(value) > MAX_KDF_CHARS:
        raise HTTPException(status_code=400, detail="kdf is too large.")
    # Format is "<algo>$<iterations>$<saltB64>"; we don't trust it for security, just sanity.
    if "$" not in value:
        raise HTTPException(status_code=400, detail="kdf format is invalid.")
    return value


class E2ESetupRequest(BaseModel):
    kdf: str = Field(..., description="Public KDF params, e.g. pbkdf2-sha256$600000$<saltB64>")
    wrapped_master_key: str = Field(..., description="Master key wrapped by the passphrase-derived key (base64)")
    recovery_wrapped_master_key: str = Field(..., description="Master key wrapped by the recovery-code-derived key (base64)")


class E2ERotateRequest(BaseModel):
    kdf: str
    wrapped_master_key: str
    # Optional: rotate the recovery wrap at the same time (e.g. issue a fresh recovery code).
    recovery_wrapped_master_key: Optional[str] = None


class E2EVaultResponse(BaseModel):
    enabled: bool
    kdf: Optional[str] = None
    wrapped_master_key: Optional[str] = None
    recovery_wrapped_master_key: Optional[str] = None


@router.get("/vault", response_model=E2EVaultResponse)
def get_vault(
    request: Request,
    current_user: models.User = Depends(get_current_active_user),
):
    """Return the user's wrapped key blobs so the browser can unlock with the passphrase."""
    _enforce_rate_limit_or_429(request, "e2e.vault", E2E_READ_RATE_LIMIT, E2E_READ_RATE_WINDOW_SECONDS)
    if not getattr(current_user, "e2e_enabled", False):
        return E2EVaultResponse(enabled=False)
    return E2EVaultResponse(
        enabled=True,
        kdf=current_user.e2e_kdf,
        wrapped_master_key=current_user.e2e_wrapped_master_key,
        recovery_wrapped_master_key=current_user.e2e_recovery_wrapped_master_key,
    )


@router.post("/setup", response_model=E2EVaultResponse)
def setup_vault(
    payload: E2ESetupRequest,
    request: Request,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """First-time vault creation. Rejects if E2E is already set up (use rotate/recover instead)."""
    _enforce_rate_limit_or_429(request, "e2e.setup", E2E_WRITE_RATE_LIMIT, E2E_WRITE_RATE_WINDOW_SECONDS)
    if getattr(current_user, "e2e_enabled", False):
        raise HTTPException(
            status_code=409,
            detail="End-to-end encryption is already set up. Use passphrase change or recovery instead.",
        )

    kdf = _validate_kdf(payload.kdf)
    wrapped = _validate_blob(payload.wrapped_master_key, "wrapped_master_key")
    recovery = _validate_blob(payload.recovery_wrapped_master_key, "recovery_wrapped_master_key")

    current_user.e2e_kdf = kdf
    current_user.e2e_wrapped_master_key = wrapped
    current_user.e2e_recovery_wrapped_master_key = recovery
    current_user.e2e_enabled = True
    current_user.e2e_setup_at = datetime.utcnow()
    db.commit()
    logger.info("E2E vault created for user_id=%s", current_user.id)
    return E2EVaultResponse(
        enabled=True, kdf=kdf, wrapped_master_key=wrapped, recovery_wrapped_master_key=recovery
    )


def _apply_rewrap(payload: E2ERotateRequest, current_user: models.User, db: Session) -> E2EVaultResponse:
    """Swap in a new passphrase wrap (and optionally a new recovery wrap) for an enabled vault.

    The server can't verify the old passphrase or recovery code — that's the point of
    zero-knowledge. The browser proves possession by being able to unwrap the master key
    before calling this; the authenticated user is simply replacing their own wrapped blobs.
    """
    if not getattr(current_user, "e2e_enabled", False):
        raise HTTPException(status_code=409, detail="End-to-end encryption is not set up yet.")

    kdf = _validate_kdf(payload.kdf)
    wrapped = _validate_blob(payload.wrapped_master_key, "wrapped_master_key")
    current_user.e2e_kdf = kdf
    current_user.e2e_wrapped_master_key = wrapped
    if payload.recovery_wrapped_master_key is not None:
        current_user.e2e_recovery_wrapped_master_key = _validate_blob(
            payload.recovery_wrapped_master_key, "recovery_wrapped_master_key"
        )
    db.commit()
    return E2EVaultResponse(
        enabled=True,
        kdf=current_user.e2e_kdf,
        wrapped_master_key=current_user.e2e_wrapped_master_key,
        recovery_wrapped_master_key=current_user.e2e_recovery_wrapped_master_key,
    )


@router.post("/rotate-passphrase", response_model=E2EVaultResponse)
def rotate_passphrase(
    payload: E2ERotateRequest,
    request: Request,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Replace the passphrase wrap after the browser re-wrapped the master key with a new passphrase."""
    _enforce_rate_limit_or_429(request, "e2e.rotate", E2E_WRITE_RATE_LIMIT, E2E_WRITE_RATE_WINDOW_SECONDS)
    result = _apply_rewrap(payload, current_user, db)
    logger.info("E2E passphrase rotated for user_id=%s", current_user.id)
    return result


@router.post("/recover", response_model=E2EVaultResponse)
def recover_passphrase(
    payload: E2ERotateRequest,
    request: Request,
    current_user: models.User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
):
    """Replace the passphrase wrap after the browser unlocked the master key via the recovery code."""
    _enforce_rate_limit_or_429(request, "e2e.recover", E2E_WRITE_RATE_LIMIT, E2E_WRITE_RATE_WINDOW_SECONDS)
    result = _apply_rewrap(payload, current_user, db)
    logger.info("E2E vault recovered (passphrase reset via recovery code) for user_id=%s", current_user.id)
    return result
