"""
Private object storage for enterprise client documents.

Documents (passports, financial proofs, I-20s, …) are sensitive, so they are
stored with unguessable keys and are ONLY served back through an authenticated,
org-scoped download endpoint — never via a public URL.

Backends:
  * Cloudflare R2 (default, production) — reuses the existing R2 credentials.
  * Local directory — used when ENTERPRISE_DOCS_DIR is set (handy for local dev
    and tests so we never write to the real bucket).
"""

import os
from pathlib import Path
from typing import Optional

from app.utils.secure_artifacts import encrypt_artifact_bytes, decrypt_artifact_bytes


class DocumentNotFound(Exception):
    """The object is not in storage — a PERMANENT condition, not a transient outage.

    Raised so a caller can tell "the bytes are gone" (nothing to retry, tell the user the
    file is unavailable) apart from a network/credential blip (retriable). Any other
    exception from the storage backend keeps its original type and means "try again"."""

LOCAL_DIR = os.getenv("ENTERPRISE_DOCS_DIR", "").strip()

# R2 / S3 config (same credentials the image uploader uses).
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "").strip()
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "images").strip()
R2_ENDPOINT_URL = os.getenv(
    "R2_ENDPOINT_URL",
    f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else "",
).strip()

_r2_client = None


def _local_path(key: str) -> Path:
    base = Path(LOCAL_DIR)
    safe = key.replace("..", "_")
    return base / safe


def _client():
    global _r2_client
    if _r2_client is None:
        import boto3
        _r2_client = boto3.client(
            "s3",
            endpoint_url=R2_ENDPOINT_URL,
            aws_access_key_id=R2_ACCESS_KEY_ID,
            aws_secret_access_key=R2_SECRET_ACCESS_KEY,
            region_name="auto",
        )
    return _r2_client


def is_configured() -> bool:
    if LOCAL_DIR:
        return True
    return bool(R2_ACCESS_KEY_ID and R2_SECRET_ACCESS_KEY and R2_ENDPOINT_URL)


def store_document(key: str, data: bytes, content_type: Optional[str] = None) -> None:
    # Encrypt at rest: the bytes written to R2 are ciphertext, so a bucket or
    # credential leak does not expose document contents. The server decrypts on read.
    payload = encrypt_artifact_bytes(data)
    if LOCAL_DIR:
        path = _local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return
    _client().put_object(
        Bucket=R2_BUCKET_NAME,
        Key=key,
        Body=payload,
        ContentType="application/octet-stream",  # opaque ciphertext
    )


def fetch_document(key: str) -> bytes:
    if LOCAL_DIR:
        try:
            raw = _local_path(key).read_bytes()
        except FileNotFoundError as exc:
            raise DocumentNotFound(key) from exc
    else:
        client = _client()
        try:
            resp = client.get_object(Bucket=R2_BUCKET_NAME, Key=key)
        except Exception as exc:
            # boto3 raises ClientError for a missing key (NoSuchKey / 404). Treat only that
            # as permanent; anything else (throttling, network, auth) is transient and
            # keeps its original type so the caller answers "try again".
            if _is_missing_object_error(exc):
                raise DocumentNotFound(key) from exc
            raise
        raw = resp["Body"].read()
    # decrypt_artifact_bytes transparently returns legacy plaintext unchanged.
    return decrypt_artifact_bytes(raw)


def _is_missing_object_error(exc: Exception) -> bool:
    """True ONLY when a boto3 error means this specific object does not exist.

    Everything else — timeouts, dropped connections, throttling, auth, a missing/renamed
    bucket — is transient or infrastructural and must be treated as retriable ("try again"),
    never as a permanent per-file 410 that tells the user to re-upload an intact file.

    Defensive on shape: several botocore transient exceptions (ReadTimeoutError,
    ConnectionClosedError, HTTPClientError) HAVE a `.response` attribute whose value is
    `None`, so a naive `getattr(exc, "response", {})` returns None and `.get()` would crash.
    NoSuchBucket is deliberately NOT here — a missing bucket is a config/infra failure, not
    a deleted document.
    """
    response = getattr(exc, "response", None)
    if not isinstance(response, dict):
        # No usable error metadata. Fall back to the class name so a real NoSuchKey
        # (should always carry a dict, but be safe) is still caught; anything else is transient.
        return exc.__class__.__name__ == "NoSuchKey"
    # The error CODE is the only reliable discriminator: get_object on a missing key raises
    # code "NoSuchKey", while a missing/renamed bucket raises "NoSuchBucket" — and BOTH carry
    # HTTP 404, so keying off the status alone would tell every user to re-upload intact files
    # whenever the bucket is misconfigured. Any other named code (NoSuchBucket, SlowDown,
    # AccessDenied, InternalError, …) is infra/transient, not a deleted document.
    code = (response.get("Error") or {}).get("Code")
    if code == "NoSuchKey":
        return True
    if code:
        return False
    # No error code at all — some S3-compatible stores answer a bare 404. Trust the status only here.
    return (response.get("ResponseMetadata") or {}).get("HTTPStatusCode") == 404


def delete_document(key: str) -> None:
    try:
        if LOCAL_DIR:
            p = _local_path(key)
            if p.exists():
                p.unlink()
            return
        _client().delete_object(Bucket=R2_BUCKET_NAME, Key=key)
    except Exception:
        # Best-effort: never block a DB delete because the blob is already gone.
        pass
