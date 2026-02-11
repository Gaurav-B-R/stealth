import hashlib
import hmac

TOKEN_HASH_PREFIX = "sha256$"


def hash_token(token: str) -> str:
    """Return a deterministic hash suitable for storing auth tokens."""
    if not token:
        return ""
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return f"{TOKEN_HASH_PREFIX}{digest}"


def is_hashed_token(value: str | None) -> bool:
    if not value:
        return False
    return value.startswith(TOKEN_HASH_PREFIX) and len(value) == len(TOKEN_HASH_PREFIX) + 64


def token_matches(raw_token: str, stored_value: str | None) -> bool:
    """
    Constant-time token check with legacy plaintext fallback support.
    Legacy fallback allows seamless transition for existing rows and links.
    """
    if not raw_token or not stored_value:
        return False

    if is_hashed_token(stored_value):
        return hmac.compare_digest(hash_token(raw_token), stored_value)

    # Legacy plaintext comparison path (temporary compatibility).
    return hmac.compare_digest(raw_token, stored_value)
