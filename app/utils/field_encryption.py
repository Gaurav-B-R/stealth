"""Transparent application-level encryption for sensitive PII columns.

Used to store high-sensitivity identifiers (e.g. enterprise client passport numbers)
as ciphertext at rest instead of plaintext, so a database dump alone does not expose
them. Key material is shared with secure_artifacts: a dedicated FIELD_ENCRYPTION_KEY
if set, else ARTIFACT_ENCRYPTION_KEY, else SECRET_KEY.

Backward-compatible: legacy plaintext values (which do not carry the version prefix)
are read back unchanged, so this can be applied to an existing column with no data
migration. Values become ciphertext the next time the row is written; a one-off
backfill can re-save existing rows to encrypt them proactively.

Trade-off: because the ciphertext is non-deterministic (random IV per encrypt), an
encrypted column cannot be used for substring/LIKE search. Remove such columns from
search filters when you encrypt them.
"""
import base64
import hashlib
import logging
import os

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import TypeDecorator, Text

logger = logging.getLogger(__name__)

_FIELD_PREFIX = "RILONO_PII_ENC_V1:"

_DEDICATED_FIELD_KEY = os.getenv("FIELD_ENCRYPTION_KEY", "").strip()
_FIELD_SECRET = (
    _DEDICATED_FIELD_KEY
    or os.getenv("ARTIFACT_ENCRYPTION_KEY", "").strip()
    or os.getenv("SECRET_KEY", "").strip()
)

_field_fernet = None
if _FIELD_SECRET:
    _field_key = base64.urlsafe_b64encode(hashlib.sha256(_FIELD_SECRET.encode("utf-8")).digest())
    _field_fernet = Fernet(_field_key)
else:
    # No secret configured (e.g. a bare local/test env). We degrade to plaintext rather
    # than crash, but warn loudly — production must set a key so PII is encrypted.
    logger.warning(
        "No FIELD_ENCRYPTION_KEY/ARTIFACT_ENCRYPTION_KEY/SECRET_KEY set; sensitive PII "
        "columns will be stored as PLAINTEXT. Set a key to encrypt them at rest."
    )


def encrypt_pii(value):
    """Encrypt a PII string for storage. None/'' pass through; already-encrypted or
    unkeyed values are returned unchanged."""
    if value is None:
        return None
    text = str(value)
    if text == "" or _field_fernet is None or text.startswith(_FIELD_PREFIX):
        return text
    token = _field_fernet.encrypt(text.encode("utf-8")).decode("ascii")
    return _FIELD_PREFIX + token


def decrypt_pii(value):
    """Decrypt a stored PII string. Legacy plaintext (no prefix) is returned as-is."""
    if value is None:
        return None
    text = str(value)
    if not text.startswith(_FIELD_PREFIX) or _field_fernet is None:
        return text
    token = text[len(_FIELD_PREFIX):]
    try:
        return _field_fernet.decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error("Failed to decrypt an encrypted PII field; returning stored value.")
        return text


class EncryptedString(TypeDecorator):
    """A column whose value is transparently encrypted at rest via Fernet.

    Stored as TEXT because ciphertext is larger than the plaintext. Backward-compatible
    with legacy plaintext rows (read back unchanged).
    """

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return encrypt_pii(value)

    def process_result_value(self, value, dialect):
        return decrypt_pii(value)
