"""
Sync eligible Rilono users from the app database into a Resend Audience.

Usage:
  python -m app.services.resend_contacts_sync
  python -m app.services.resend_contacts_sync --dry-run
  python -m app.services.resend_contacts_sync --limit 500
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import requests

from app import models
from app.database import SessionLocal


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _safe_positive_int(value: str | None, default: int) -> int:
    raw = str(value or "").strip()
    if not raw:
        return default
    try:
        parsed = int(raw)
    except ValueError:
        return default
    return parsed if parsed > 0 else default


RESEND_API_KEY = (os.getenv("RESEND_API_KEY", "").strip() or None)
RESEND_API_BASE_URL = (os.getenv("RESEND_API_BASE_URL", "https://api.resend.com").strip() or "https://api.resend.com").rstrip("/")
# Resend renamed "Audiences" to "Segments"; keep audience env for backward compatibility.
RESEND_MARKETING_SEGMENT_ID = (os.getenv("RESEND_MARKETING_SEGMENT_ID", "").strip() or None)
RESEND_MARKETING_AUDIENCE_ID = (os.getenv("RESEND_MARKETING_AUDIENCE_ID", "").strip() or None)
RESEND_CONTACTS_SYNC_BATCH_SIZE = min(
    100,
    _safe_positive_int(os.getenv("RESEND_CONTACTS_SYNC_BATCH_SIZE"), default=100),
)
RESEND_CONTACTS_SYNC_TIMEOUT_SECONDS = _safe_positive_int(
    os.getenv("RESEND_CONTACTS_SYNC_TIMEOUT_SECONDS"),
    default=30,
)
RESEND_CONTACTS_SYNC_REQUEST_INTERVAL_SECONDS = max(
    0.0,
    float(os.getenv("RESEND_CONTACTS_SYNC_REQUEST_INTERVAL_SECONDS", "0.55") or "0.55"),
)
RESEND_CONTACTS_SYNC_MAX_RETRIES = max(
    0,
    _safe_positive_int(os.getenv("RESEND_CONTACTS_SYNC_MAX_RETRIES"), default=4),
)
RESEND_CONTACTS_SYNC_RETRY_MAX_SECONDS = max(
    1.0,
    float(os.getenv("RESEND_CONTACTS_SYNC_RETRY_MAX_SECONDS", "6") or "6"),
)
# Compatibility flag: when enabled, remove ineligible users from the marketing
# segment only. Do not mark contacts as provider-unsubscribed, because password
# reset and verification emails are transactional and must remain deliverable.
RESEND_CONTACTS_SYNC_UNSUBSCRIBE_INELIGIBLE = _is_truthy(
    os.getenv("RESEND_CONTACTS_SYNC_UNSUBSCRIBE_INELIGIBLE", "false")
)

_LAST_REQUEST_AT_MONOTONIC = 0.0


@dataclass
class SyncStats:
    status: str
    scanned_users: int = 0
    eligible_users: int = 0
    known_contacts: int = 0
    created_contacts: int = 0
    updated_contacts: int = 0
    segment_added_contacts: int = 0
    unsubscribed_contacts: int = 0
    segment_removed_contacts: int = 0
    skipped_contacts: int = 0
    error_count: int = 0
    errors: list[str] | None = None
    dry_run: bool = False
    segment_id: str = ""
    limit: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "dry_run": self.dry_run,
            "segment_id": self.segment_id,
            "limit": self.limit,
            "scanned_users": self.scanned_users,
            "eligible_users": self.eligible_users,
            "known_contacts": self.known_contacts,
            "created_contacts": self.created_contacts,
            "updated_contacts": self.updated_contacts,
            "segment_added_contacts": self.segment_added_contacts,
            "unsubscribed_contacts": self.unsubscribed_contacts,
            "segment_removed_contacts": self.segment_removed_contacts,
            "skipped_contacts": self.skipped_contacts,
            "error_count": self.error_count,
            "errors": self.errors or [],
        }


def _split_name(full_name: str | None) -> tuple[str | None, str | None]:
    parts = [chunk for chunk in str(full_name or "").strip().split() if chunk]
    if not parts:
        return (None, None)
    if len(parts) == 1:
        return (parts[0], None)
    return (parts[0], " ".join(parts[1:]))


def _normalize_email(email: str | None) -> str:
    return str(email or "").strip().lower()


def _encode_contact_path_value(value: str) -> str:
    return quote(str(value or "").strip(), safe="")


def _resend_request(
    session: requests.Session,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    url = f"{RESEND_API_BASE_URL}{path}"
    method_upper = method.upper()
    attempts = 0

    while True:
        _wait_for_client_rate_limit()

        response = None
        data: dict[str, Any] | None = None
        try:
            response = session.request(
                method=method_upper,
                url=url,
                params=params,
                json=payload,
                timeout=RESEND_CONTACTS_SYNC_TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            if attempts < RESEND_CONTACTS_SYNC_MAX_RETRIES:
                _sleep_for_retry(attempt=attempts, retry_after_header=None)
                attempts += 1
                continue
            raise RuntimeError(f"{method_upper} {path} failed: {str(exc)}") from exc

        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                data = parsed
            else:
                data = {"data": parsed}
        except ValueError:
            data = {"message": response.text}

        if response.status_code == 429 and attempts < RESEND_CONTACTS_SYNC_MAX_RETRIES:
            _sleep_for_retry(attempt=attempts, retry_after_header=response.headers.get("Retry-After"))
            attempts += 1
            continue

        if response.status_code >= 500 and attempts < RESEND_CONTACTS_SYNC_MAX_RETRIES:
            _sleep_for_retry(attempt=attempts, retry_after_header=None)
            attempts += 1
            continue

        if response.ok:
            if isinstance(data, dict):
                return data
            return {"data": data}

        message = ""
        if isinstance(data, dict):
            message = str(data.get("message") or data.get("error") or "").strip()
        if not message:
            message = f"HTTP {response.status_code}"
        raise RuntimeError(f"{method_upper} {path} failed: {message}")


def _wait_for_client_rate_limit() -> None:
    global _LAST_REQUEST_AT_MONOTONIC
    interval = max(0.0, RESEND_CONTACTS_SYNC_REQUEST_INTERVAL_SECONDS)
    if interval <= 0:
        return
    now = time.monotonic()
    elapsed = now - _LAST_REQUEST_AT_MONOTONIC
    if elapsed < interval:
        time.sleep(interval - elapsed)
    _LAST_REQUEST_AT_MONOTONIC = time.monotonic()


def _sleep_for_retry(attempt: int, retry_after_header: str | None) -> None:
    retry_after_seconds = _parse_retry_after_seconds(retry_after_header)
    if retry_after_seconds is not None:
        time.sleep(min(retry_after_seconds, RESEND_CONTACTS_SYNC_RETRY_MAX_SECONDS))
        return

    # Exponential backoff + jitter.
    base = min(0.5 * (2**attempt), RESEND_CONTACTS_SYNC_RETRY_MAX_SECONDS)
    jitter = random.uniform(0.05, 0.25)
    time.sleep(min(base + jitter, RESEND_CONTACTS_SYNC_RETRY_MAX_SECONDS))


def _parse_retry_after_seconds(value: str | None) -> float | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = float(raw)
        if parsed <= 0:
            return None
        return parsed
    except ValueError:
        return None


def _build_resend_session() -> requests.Session:
    if not RESEND_API_KEY:
        raise RuntimeError("RESEND_API_KEY is missing.")
    session = requests.Session()
    session.headers.update(
        {
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        }
    )
    return session


def _list_contacts(session: requests.Session) -> list[dict[str, Any]]:
    contacts: list[dict[str, Any]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()

    while True:
        params: dict[str, Any] = {
            "limit": RESEND_CONTACTS_SYNC_BATCH_SIZE,
        }
        if cursor:
            params["after"] = cursor

        response = _resend_request(session, "GET", "/contacts", params=params)
        batch = response.get("data")
        if not isinstance(batch, list) or not batch:
            break

        contacts.extend(batch)

        next_cursor = str(
            response.get("next")
            or response.get("next_cursor")
            or ""
        ).strip()
        if next_cursor:
            if next_cursor in seen_cursors:
                break
            seen_cursors.add(next_cursor)
            cursor = next_cursor
            continue

        has_more = bool(response.get("has_more") or response.get("hasMore"))
        if has_more:
            fallback_cursor = str(batch[-1].get("id") or "").strip()
            if not fallback_cursor or fallback_cursor in seen_cursors:
                break
            seen_cursors.add(fallback_cursor)
            cursor = fallback_cursor
            continue

        break

    return contacts


def _add_contact_to_segment(session: requests.Session, *, email: str, segment_id: str) -> None:
    encoded = _encode_contact_path_value(email)
    _resend_request(
        session,
        "POST",
        f"/contacts/{encoded}/segments/{segment_id}",
    )


def _remove_contact_from_segment(session: requests.Session, *, email: str, segment_id: str) -> None:
    encoded = _encode_contact_path_value(email)
    _resend_request(
        session,
        "DELETE",
        f"/contacts/{encoded}/segments/{segment_id}",
    )


def _list_contact_segments(session: requests.Session, *, email: str) -> list[dict[str, Any]]:
    encoded = _encode_contact_path_value(email)
    response = _resend_request(session, "GET", f"/contacts/{encoded}/segments")
    data = response.get("data")
    return data if isinstance(data, list) else []


def _load_eligible_users(limit: int = 0) -> list[models.User]:
    db = SessionLocal()
    try:
        query = (
            db.query(models.User)
            .filter(
                models.User.is_active.is_(True),
                models.User.email_verified.is_(True),
                models.User.email_notifications_enabled.is_(True),
                models.User.email.isnot(None),
            )
            .order_by(models.User.id.asc())
        )
        if limit > 0:
            query = query.limit(limit)
        users = query.all()
        return users
    finally:
        db.close()


def run_resend_contacts_sync(
    *,
    audience_id: str | None = None,
    segment_id: str | None = None,
    dry_run: bool = False,
    limit: int = 0,
    unsubscribe_ineligible: bool | None = None,
) -> dict[str, Any]:
    target_segment_id = (
        segment_id
        or audience_id
        or RESEND_MARKETING_SEGMENT_ID
        or RESEND_MARKETING_AUDIENCE_ID
        or ""
    ).strip()
    if not target_segment_id:
        raise RuntimeError(
            "RESEND_MARKETING_SEGMENT_ID (or RESEND_MARKETING_AUDIENCE_ID) is missing."
        )

    remove_ineligible_from_segment = (
        RESEND_CONTACTS_SYNC_UNSUBSCRIBE_INELIGIBLE
        if unsubscribe_ineligible is None
        else bool(unsubscribe_ineligible)
    )

    stats = SyncStats(
        status="running",
        dry_run=dry_run,
        segment_id=target_segment_id,
        limit=max(0, int(limit or 0)),
        errors=[],
    )

    session = _build_resend_session()
    known_contacts = _list_contacts(session)
    stats.known_contacts = len(known_contacts)

    contacts_by_email: dict[str, dict[str, Any]] = {}
    for contact in known_contacts:
        normalized_email = _normalize_email(contact.get("email"))
        if normalized_email:
            contacts_by_email[normalized_email] = contact

    eligible_users = _load_eligible_users(limit=stats.limit)
    stats.scanned_users = len(eligible_users)

    eligible_by_email: dict[str, models.User] = {}
    for user in eligible_users:
        normalized_email = _normalize_email(user.email)
        if not normalized_email:
            continue
        eligible_by_email[normalized_email] = user
    stats.eligible_users = len(eligible_by_email)

    for email, user in eligible_by_email.items():
        existing = contacts_by_email.get(email)
        first_name, last_name = _split_name(user.full_name)

        if existing:
            needs_segment_assignment = True
            should_update = False
            update_payload: dict[str, Any] = {}
            existing_first = str(existing.get("first_name") or "").strip()
            existing_last = str(existing.get("last_name") or "").strip()
            existing_unsubscribed = bool(existing.get("unsubscribed"))

            target_first = str(first_name or "").strip()
            target_last = str(last_name or "").strip()

            if target_first != existing_first:
                update_payload["first_name"] = target_first or None
                should_update = True
            if target_last != existing_last:
                update_payload["last_name"] = target_last or None
                should_update = True
            if existing_unsubscribed:
                update_payload["unsubscribed"] = False
                should_update = True

            if not should_update:
                stats.skipped_contacts += 1
            elif dry_run:
                stats.updated_contacts += 1
            else:
                contact_id = str(existing.get("id") or "").strip()
                if not contact_id:
                    stats.error_count += 1
                    stats.errors.append(f"Missing contact id for email={email}")
                    needs_segment_assignment = False
                else:
                    try:
                        _resend_request(
                            session,
                            "PATCH",
                            f"/contacts/{contact_id}",
                            payload=update_payload,
                        )
                        stats.updated_contacts += 1
                    except Exception as exc:  # noqa: BLE001
                        stats.error_count += 1
                        stats.errors.append(f"Update failed for {email}: {str(exc)}")

            if needs_segment_assignment:
                if dry_run:
                    stats.segment_added_contacts += 1
                else:
                    try:
                        _add_contact_to_segment(session, email=email, segment_id=target_segment_id)
                        stats.segment_added_contacts += 1
                    except Exception as exc:  # noqa: BLE001
                        # Best-effort: if API says already in segment, do not treat as error.
                        message = str(exc).lower()
                        if "already" in message and "segment" in message:
                            stats.skipped_contacts += 1
                        else:
                            stats.error_count += 1
                            stats.errors.append(f"Add-to-segment failed for {email}: {str(exc)}")
            continue

        create_payload = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "unsubscribed": False,
            "segments": [{"id": target_segment_id}],
        }

        if dry_run:
            stats.created_contacts += 1
            stats.segment_added_contacts += 1
            continue

        try:
            _resend_request(session, "POST", "/contacts", payload=create_payload)
            stats.created_contacts += 1
            stats.segment_added_contacts += 1
        except Exception as exc:  # noqa: BLE001
            stats.error_count += 1
            stats.errors.append(f"Create failed for {email}: {str(exc)}")
            continue

        continue

    if remove_ineligible_from_segment:
        eligible_emails = set(eligible_by_email.keys())
        for email, contact in contacts_by_email.items():
            if email in eligible_emails:
                continue

            in_target_segment = False
            if not dry_run:
                try:
                    segments = _list_contact_segments(session, email=email)
                    in_target_segment = any(
                        str(segment.get("id") or "").strip() == target_segment_id
                        for segment in segments
                    )
                except Exception as exc:  # noqa: BLE001
                    stats.error_count += 1
                    stats.errors.append(f"List-segments failed for {email}: {str(exc)}")
                    continue
            else:
                in_target_segment = True

            if not in_target_segment:
                continue

            if dry_run:
                stats.segment_removed_contacts += 1
                continue

            try:
                _remove_contact_from_segment(session, email=email, segment_id=target_segment_id)
                stats.segment_removed_contacts += 1
            except Exception as exc:  # noqa: BLE001
                stats.error_count += 1
                stats.errors.append(f"Segment removal failed for {email}: {str(exc)}")

    stats.status = "completed" if stats.error_count == 0 else "completed_with_errors"
    return stats.to_dict()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sync eligible app users into a Resend Audience contacts list."
    )
    parser.add_argument(
        "--audience-id",
        default="",
        help="Legacy alias for segment id override.",
    )
    parser.add_argument(
        "--segment-id",
        default="",
        help="Override RESEND_MARKETING_SEGMENT_ID for this run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compute changes without calling Resend write endpoints.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit number of eligible users read from DB (0 = no limit).",
    )
    parser.add_argument(
        "--unsubscribe-ineligible",
        action="store_true",
        help="Remove contacts not currently eligible from the marketing segment without provider-unsubscribing them.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    try:
        result = run_resend_contacts_sync(
            audience_id=args.audience_id or None,
            segment_id=args.segment_id or None,
            dry_run=bool(args.dry_run),
            limit=max(0, int(args.limit or 0)),
            unsubscribe_ineligible=bool(args.unsubscribe_ineligible),
        )
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"status": "failed", "error": str(exc)}))
        return 1

    print(json.dumps(result, default=str))
    return 0 if result.get("status") in {"completed", "completed_with_errors"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
