import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken


ARTIFACT_PREFIX = b"RILONO_ARTIFACT_ENC_V1:"
_ARTIFACT_SECRET = (
    os.getenv("ARTIFACT_ENCRYPTION_KEY", "").strip()
    or os.getenv("SECRET_KEY", "").strip()
)

if not _ARTIFACT_SECRET:
    raise RuntimeError(
        "ARTIFACT_ENCRYPTION_KEY or SECRET_KEY must be set to encrypt artifact data."
    )

_artifact_key = base64.urlsafe_b64encode(hashlib.sha256(_ARTIFACT_SECRET.encode("utf-8")).digest())
_artifact_fernet = Fernet(_artifact_key)


def encrypt_artifact_bytes(data: bytes) -> bytes:
    """Encrypt derived artifact bytes before storing in object storage."""
    return ARTIFACT_PREFIX + _artifact_fernet.encrypt(data)


def decrypt_artifact_bytes(data: bytes) -> bytes:
    """
    Decrypt derived artifact bytes.
    Legacy fallback: if payload is not prefixed, treat it as plaintext.
    """
    if not data:
        return data
    if not data.startswith(ARTIFACT_PREFIX):
        return data

    token = data[len(ARTIFACT_PREFIX):]
    try:
        return _artifact_fernet.decrypt(token)
    except InvalidToken as exc:
        raise ValueError("Encrypted artifact payload could not be decrypted") from exc
