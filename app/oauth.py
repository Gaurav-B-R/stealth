"""
Social login (OAuth 2.0 / OIDC) for the B2C student app — Google, Microsoft, Apple.

Each provider is OFF until its credentials are present in the environment, so this
module is safe to ship before any provider is configured (the frontend only shows
buttons for `enabled_providers()`). The auth router drives the redirect/callback;
this module owns provider config, the authorize URL, the code→token exchange, and
turning a provider response into a verified {email, name, sub}.

Required env per provider (set in your hosting env panel, not committed):
  Google:    GOOGLE_OAUTH_CLIENT_ID, GOOGLE_OAUTH_CLIENT_SECRET
  Microsoft: MICROSOFT_OAUTH_CLIENT_ID, MICROSOFT_OAUTH_CLIENT_SECRET
  Apple:     APPLE_OAUTH_CLIENT_ID (Services ID), APPLE_OAUTH_TEAM_ID,
             APPLE_OAUTH_KEY_ID, APPLE_OAUTH_PRIVATE_KEY (.p8 PEM contents)

Redirect URI registered with each provider must be:
  {OAUTH_REDIRECT_BASE_URL or BASE_URL}/api/auth/oauth/{provider}/callback
"""

from __future__ import annotations

import os
import time
import json
import logging
from typing import Optional
from urllib.parse import urlencode

import requests
from jose import jwt as jose_jwt

logger = logging.getLogger(__name__)

BASE_URL = (os.getenv("OAUTH_REDIRECT_BASE_URL", "").strip()
            or os.getenv("BASE_URL", "https://rilono.com").strip()
            or "https://rilono.com").rstrip("/")

GOOGLE_DISCOVERY_ISS = "https://accounts.google.com"
APPLE_KEYS_URL = "https://appleid.apple.com/auth/keys"


PROVIDERS: dict[str, dict] = {
    "google": {
        "label": "Google",
        "authorize_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "userinfo_url": "https://openidconnect.googleapis.com/v1/userinfo",
        "scope": "openid email profile",
        "extra_authorize": {"access_type": "online", "prompt": "select_account"},
        "response_mode": None,
    },
    "microsoft": {
        "label": "Microsoft",
        "authorize_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "userinfo_url": "https://graph.microsoft.com/oidc/userinfo",
        "scope": "openid email profile",
        "extra_authorize": {},
        "response_mode": None,
    },
    "apple": {
        "label": "Apple",
        "authorize_url": "https://appleid.apple.com/auth/authorize",
        "token_url": "https://appleid.apple.com/auth/token",
        "userinfo_url": None,  # Apple has no userinfo endpoint — decode the id_token
        "scope": "name email",
        "extra_authorize": {"response_mode": "form_post"},
        "response_mode": "form_post",
    },
}


def _env(key: str) -> str:
    return (os.getenv(key, "") or "").strip()


def client_id(provider: str) -> str:
    return _env(f"{provider.upper()}_OAUTH_CLIENT_ID")


def _apple_client_secret() -> Optional[str]:
    team_id = _env("APPLE_OAUTH_TEAM_ID")
    key_id = _env("APPLE_OAUTH_KEY_ID")
    private_key = _env("APPLE_OAUTH_PRIVATE_KEY").replace("\\n", "\n")
    cid = client_id("apple")
    if not (team_id and key_id and private_key and cid):
        return None
    now = int(time.time())
    try:
        return jose_jwt.encode(
            {"iss": team_id, "iat": now, "exp": now + 60 * 60 * 24 * 150,
             "aud": "https://appleid.apple.com", "sub": cid},
            private_key, algorithm="ES256", headers={"kid": key_id, "alg": "ES256"},
        )
    except Exception:
        logger.exception("Failed to build Apple client secret JWT")
        return None


def client_secret(provider: str) -> Optional[str]:
    if provider == "apple":
        return _apple_client_secret()
    return _env(f"{provider.upper()}_OAUTH_CLIENT_SECRET") or None


def is_enabled(provider: str) -> bool:
    if provider not in PROVIDERS:
        return False
    if provider == "apple":
        return bool(client_id("apple") and _apple_client_secret())
    return bool(client_id(provider) and client_secret(provider))


def enabled_providers() -> list[dict]:
    return [{"key": k, "label": PROVIDERS[k]["label"]} for k in PROVIDERS if is_enabled(k)]


def redirect_uri(provider: str) -> str:
    return f"{BASE_URL}/api/auth/oauth/{provider}/callback"


def build_authorize_url(provider: str, *, state: str, nonce: str) -> str:
    cfg = PROVIDERS[provider]
    params = {
        "client_id": client_id(provider),
        "redirect_uri": redirect_uri(provider),
        "response_type": "code",
        "scope": cfg["scope"],
        "state": state,
        "nonce": nonce,
    }
    params.update(cfg.get("extra_authorize") or {})
    return f"{cfg['authorize_url']}?{urlencode(params)}"


def exchange_code(provider: str, code: str) -> dict:
    cfg = PROVIDERS[provider]
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri(provider),
        "client_id": client_id(provider),
        "client_secret": client_secret(provider) or "",
    }
    resp = requests.post(
        cfg["token_url"], data=data,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )
    if resp.status_code >= 400:
        logger.warning("OAuth token exchange failed (%s): %s", provider, resp.text[:300])
        raise RuntimeError("Could not complete sign-in with this provider.")
    return resp.json()


def _decode_apple_id_token(id_token: str) -> dict:
    """Verify Apple's id_token against Apple's JWKS and return its claims."""
    try:
        header = jose_jwt.get_unverified_header(id_token)
        jwks = requests.get(APPLE_KEYS_URL, timeout=10).json().get("keys", [])
        key = next((k for k in jwks if k.get("kid") == header.get("kid")), None)
        if not key:
            raise RuntimeError("Apple signing key not found.")
        return jose_jwt.decode(
            id_token, key, algorithms=[header.get("alg", "RS256")],
            audience=client_id("apple"), issuer="https://appleid.apple.com",
            options={"verify_at_hash": False},
        )
    except Exception:
        logger.exception("Apple id_token verification failed")
        raise RuntimeError("Could not verify your Apple sign-in.")


def fetch_identity(provider: str, tokens: dict, *, apple_user: Optional[str] = None) -> dict:
    """Return {email, email_verified, name, sub} from a token response. Raises if no email."""
    cfg = PROVIDERS[provider]
    email = None
    name = None
    sub = None
    email_verified = True

    if cfg["userinfo_url"]:
        access_token = tokens.get("access_token")
        if not access_token:
            raise RuntimeError("No access token returned by the provider.")
        resp = requests.get(
            cfg["userinfo_url"], headers={"Authorization": f"Bearer {access_token}"}, timeout=15
        )
        if resp.status_code >= 400:
            raise RuntimeError("Could not read your profile from the provider.")
        info = resp.json()
        email = info.get("email")
        name = info.get("name") or info.get("given_name")
        sub = info.get("sub")
        ev = info.get("email_verified")
        email_verified = (ev is True or str(ev).lower() == "true") if ev is not None else True
    else:
        # Apple — claims come from the id_token; name only on first consent (form_post `user`).
        claims = _decode_apple_id_token(tokens.get("id_token") or "")
        email = claims.get("email")
        sub = claims.get("sub")
        ev = claims.get("email_verified")
        email_verified = (ev is True or str(ev).lower() == "true") if ev is not None else True
        if apple_user:
            try:
                u = json.loads(apple_user)
                nm = u.get("name") or {}
                name = " ".join(p for p in [nm.get("firstName"), nm.get("lastName")] if p).strip() or None
            except Exception:
                name = None

    email = (email or "").strip().lower()
    if not email:
        raise RuntimeError("Your provider account didn't share an email address.")
    return {"email": email, "email_verified": bool(email_verified), "name": name, "sub": sub}
