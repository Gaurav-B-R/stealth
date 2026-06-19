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
        raw = _local_path(key).read_bytes()
    else:
        resp = _client().get_object(Bucket=R2_BUCKET_NAME, Key=key)
        raw = resp["Body"].read()
    # decrypt_artifact_bytes transparently returns legacy plaintext unchanged.
    return decrypt_artifact_bytes(raw)


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
