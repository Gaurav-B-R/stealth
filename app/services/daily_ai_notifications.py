import json
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import boto3
from botocore.config import Config
from pydantic import BaseModel, ValidationError
from sqlalchemy import and_, exists, func, not_
from sqlalchemy.exc import IntegrityError

from app import models
from app import visa_catalog
from app.database import SessionLocal
from app.email_service import (
    build_email_notifications_unsubscribe_url,
    send_proactive_assistant_email,
)
from app.notification_center import create_user_notification
from app.routers.documents import refresh_student_profile_snapshot_for_user
from app.utils import gemini_service as gemini_utils
from app.utils.secure_artifacts import decrypt_artifact_bytes

MODEL_CANDIDATES = gemini_utils.get_model_candidates(
    primary_env="DAILY_AI_NOTIFIER_MODEL",
    candidates_env="DAILY_AI_NOTIFIER_MODEL_CANDIDATES",
)
MODEL_NAME = MODEL_CANDIDATES[0]
PROFILE_KEY_SUFFIX = "STUDENT_PROFILE_AND_F1_VISA_STATUS.json"
PROMPT_LOG_MAX_CHARS = int(os.getenv("GEMINI_LOG_MAX_CHARS", "0") or "0")

R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "")
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "")
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "")
R2_DOCUMENTS_BUCKET = os.getenv("R2_DOCUMENTS_BUCKET", "documents")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com")

DAILY_AI_NOTIFIER_ENABLED = str(os.getenv("DAILY_AI_NOTIFIER_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}
DAILY_AI_NOTIFIER_HOUR_UTC = max(0, min(23, int(os.getenv("DAILY_AI_NOTIFIER_HOUR_UTC", "6") or "6")))
DAILY_AI_NOTIFIER_MINUTE_UTC = max(0, min(59, int(os.getenv("DAILY_AI_NOTIFIER_MINUTE_UTC", "0") or "0")))
DAILY_AI_NOTIFIER_POLL_SECONDS = max(60, int(os.getenv("DAILY_AI_NOTIFIER_POLL_SECONDS", "300") or "300"))
DAILY_AI_NOTIFIER_USER_LIMIT = max(0, int(os.getenv("DAILY_AI_NOTIFIER_USER_LIMIT", "0") or "0"))
# Dormant accounts: once a user has gone DORMANT_AFTER_DAYS without logging in, their scan
# (the Gemini call, the R2 reads AND any email) drops from daily to once every
# DORMANT_CADENCE_DAYS. Two-thirds of this job's Gemini spend was going to accounts that
# had not logged in for 30+ days or ever (2026-09-05 audit), each of them emailed ~daily.
# A login puts the account straight back on the daily schedule.
DAILY_AI_NOTIFIER_DORMANT_AFTER_DAYS = max(0, int(os.getenv("DAILY_AI_NOTIFIER_DORMANT_AFTER_DAYS", "30") or "30"))
DAILY_AI_NOTIFIER_DORMANT_CADENCE_DAYS = max(1, int(os.getenv("DAILY_AI_NOTIFIER_DORMANT_CADENCE_DAYS", "14") or "14"))


class DailyAssistantDecision(BaseModel):
    notification_needed: bool
    reasoning: str
    email_subject: str = ""
    email_body: str = ""
    in_app_message: str = ""


class DailyAINotificationScheduler:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if not DAILY_AI_NOTIFIER_ENABLED:
            print("Daily AI notifier: disabled (DAILY_AI_NOTIFIER_ENABLED=false)")
            return
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="daily-ai-notifier",
            daemon=True,
        )
        self._thread.start()
        print(
            "Daily AI notifier: started "
            f"(schedule={DAILY_AI_NOTIFIER_HOUR_UTC:02d}:{DAILY_AI_NOTIFIER_MINUTE_UTC:02d} UTC, "
            f"poll={DAILY_AI_NOTIFIER_POLL_SECONDS}s)"
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                now_utc = datetime.now(timezone.utc)
                if _is_due_for_today(now_utc):
                    result = run_daily_ai_notification_job(force=False)
                    if result.get("status") != "skipped":
                        print(f"Daily AI notifier run result: {result}")
            except Exception as exc:  # noqa: BLE001
                print(f"Daily AI notifier loop error: {str(exc)}")
            self._stop_event.wait(DAILY_AI_NOTIFIER_POLL_SECONDS)


def _clip_for_log(text: str) -> str:
    if text is None:
        return ""
    if PROMPT_LOG_MAX_CHARS <= 0 or len(text) <= PROMPT_LOG_MAX_CHARS:
        return text
    return f"{text[:PROMPT_LOG_MAX_CHARS]}\n\n...[truncated {len(text) - PROMPT_LOG_MAX_CHARS} chars]"


def _build_r2_client():
    if not R2_ACCESS_KEY_ID or not R2_SECRET_ACCESS_KEY:
        raise RuntimeError("R2 credentials are not configured")
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


def _read_decrypted_r2_text(r2_client, key: str) -> str:
    response = r2_client.get_object(Bucket=R2_DOCUMENTS_BUCKET, Key=key)
    encrypted_blob = response["Body"].read()
    return decrypt_artifact_bytes(encrypted_blob).decode("utf-8")


def _build_gemini_model(model_name: str = MODEL_NAME):
    if not gemini_utils.is_ai_configured():
        raise RuntimeError("Gemini is not configured for the selected provider")
    if gemini_utils.USE_VERTEX_AI:
        return gemini_utils.GenerativeModel(model_name), "vertex"
    return gemini_utils.genai.GenerativeModel(model_name), "genai"


def _as_naive_utc(value: Optional[datetime]) -> Optional[datetime]:
    """users.first_login_at / last_login_at are naive UTC in prod (ALTER-added TIMESTAMP,
    written with datetime.utcnow()) but the model declares timezone=True — normalise
    both shapes so a comparison never raises (the 2026-08-23 naive/aware incident)."""
    if value is None:
        return None
    if value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _last_activity_at(user) -> Optional[datetime]:
    """Best evidence of the account being used: last login, else first login, else signup.
    A fresh signup that never logs in therefore gets the daily onboarding nudges for
    DORMANT_AFTER_DAYS and then goes to the dormant cadence like everyone else."""
    for attr in ("last_login_at", "first_login_at", "created_at"):
        stamp = _as_naive_utc(getattr(user, attr, None))
        if stamp is not None:
            return stamp
    return None


def _is_dormant(user, now_utc: datetime) -> bool:
    if DAILY_AI_NOTIFIER_DORMANT_AFTER_DAYS <= 0:
        return False
    last = _last_activity_at(user)
    if last is None:
        return True
    return (_as_naive_utc(now_utc) - last) >= timedelta(days=DAILY_AI_NOTIFIER_DORMANT_AFTER_DAYS)


def _is_user_due(user, run_date, now_utc: datetime) -> bool:
    """Active accounts are scanned every run. Dormant accounts are scanned on exactly one
    day per DORMANT_CADENCE_DAYS, chosen from the user id — stateless (no last-scanned
    column to drift), idempotent per run_date, and it spreads the dormant scans evenly
    across the fortnight instead of piling them onto one morning."""
    if not _is_dormant(user, now_utc):
        return True
    cadence = DAILY_AI_NOTIFIER_DORMANT_CADENCE_DAYS
    return run_date.toordinal() % cadence == int(user.id) % cadence


def _consumer_account_clause():
    """SQL predicate for "this user is a B2C (consumer) student account", used to keep
    Rilono Enterprise (B2B) accounts out of the daily scan.

    Enterprise staff have no student journey here — no profile snapshot worth reading, no
    visa timeline to nudge — yet every scan of one still costs a profile-snapshot rebuild,
    an R2 write, R2 reads and a Gemini call billed to the B2C bucket (pricing-model review,
    Phase 0 "stop the daily notifier scanning enterprise staff accounts"). An account is
    treated as enterprise when EITHER:
      * users.is_enterprise_account is set (workspace owners and org-created invitees —
        the same flag that blocks them from the consumer app), OR
      * it holds ANY active enterprise_organization_members row. This deliberately also
        covers a pre-existing B2C user who later joined a team (who keeps consumer access
        and so has the flag unset): once they work inside a workspace the daily student
        nudges stop. Deactivating the membership (is_active=False — the gate the member
        model documents; `status` only records why) puts them back on the schedule.
    Platform admins/developers are NOT exempt, unlike app.auth.is_enterprise_only_account:
    that exemption exists so staff can still LOG IN to the admin console; it is no reason
    to spend a daily Gemini call on a staff account that belongs to a workspace.

    Applied in SQL rather than per row so an enterprise account is never even loaded —
    nothing downstream (snapshot refresh, R2, Gemini, email) can run for it, and the
    dormancy cadence below only ever sees consumer accounts. `isnot(True)` (not `== False`)
    so a NULL flag on a legacy row counts as consumer, on both PostgreSQL and SQLite; the
    membership test is a correlated NOT EXISTS so a user in several orgs is still one row."""
    member = models.EnterpriseOrganizationMember
    has_active_membership = exists().where(
        member.user_id == models.User.id,
        member.is_active.is_(True),
    )
    return and_(
        models.User.is_enterprise_account.isnot(True),
        not_(has_active_membership),
    )


def _is_due_for_today(now_utc: datetime) -> bool:
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    target = now_utc.replace(
        hour=DAILY_AI_NOTIFIER_HOUR_UTC,
        minute=DAILY_AI_NOTIFIER_MINUTE_UTC,
        second=0,
        microsecond=0,
    )
    return now_utc >= target


def _clean_json_response(text: str) -> dict:
    value = (text or "").strip()
    if value.startswith("```json"):
        value = value[7:].strip()
    elif value.startswith("```"):
        value = value[3:].strip()
    if value.endswith("```"):
        value = value[:-3].strip()

    first_brace = value.find("{")
    last_brace = value.rfind("}")
    if first_brace == -1 or last_brace == -1 or last_brace <= first_brace:
        raise ValueError("No JSON object found in Gemini response")

    return json.loads(value[first_brace : last_brace + 1])


def _journey_context(user: models.User) -> dict:
    """Resolve the student's destination country + visa type so notifications speak to
    their actual journey (US F-1, UK Student, Canada Study Permit, Australia Subclass
    500, …) instead of assuming US F-1."""
    code, visa_type_key = visa_catalog.resolve_selection(
        getattr(user, "destination_country_code", None),
        getattr(user, "visa_type_key", None),
    )
    meta = visa_catalog.country_meta(code) or {}
    country_name = (meta.get("name") or code or "").strip() or "your destination"
    visa_label = (visa_catalog.visa_type_label(code, visa_type_key) or "").strip() or "student visa"
    return {
        "country_code": code,
        "visa_type_key": visa_type_key,
        "country_name": country_name,
        "visa_label": visa_label,
        "journey": f"{country_name} student visa ({visa_label})",
    }


def _build_analysis_prompt(user: models.User, profile_json_raw: str, document_payload: list[dict]) -> str:
    now_iso = datetime.now(timezone.utc).isoformat()
    jc = _journey_context(user)
    country_name = jc["country_name"]
    visa_label = jc["visa_label"]
    if document_payload:
        documents_text_parts: list[str] = []
        for index, doc in enumerate(document_payload, 1):
            documents_text_parts.append(
                (
                    f"--- DOCUMENT {index} ---\n"
                    f"document_type: {doc.get('document_type') or 'document'}\n"
                    f"filename: {doc.get('filename') or 'unknown'}\n"
                    f"is_valid: {doc.get('is_valid')}\n"
                    f"validation_message: {doc.get('validation_message') or ''}\n"
                    f"raw_extracted_content:\n{doc.get('content') or ''}\n"
                )
            )
        documents_raw_text = "\n".join(documents_text_parts)
    else:
        documents_raw_text = "No extracted document files found for this user."

    return f"""You are Rilono's proactive AI study-abroad assistant for a student applying to {country_name}.
This student is pursuing a {country_name} student visa ({visa_label}). Tailor EVERYTHING —
terminology, documents, stages, fees, forms and next steps — to {country_name} and this visa type.
Analyze the user's full raw profile JSON and raw extracted document files.

Current UTC datetime: {now_iso}
User context:
- user_id: {user.id}
- full_name: {user.full_name or ''}
- email: {user.email}
- current_residence_country: {getattr(user, 'current_residence_country', None) or ''}
- destination_country: {country_name}
- visa_type: {visa_label}

IMPORTANT — destination is correct and expected:
- This student's chosen destination ({country_name}) and visa type ({visa_label}) are correct. Do NOT
  treat them as an error, and do NOT assume a US F-1 visa. Never raise a "mismatch" simply because the
  destination is not the United States. Only flag a country/visa mismatch if the student's OWN profile
  and documents contradict EACH OTHER (e.g. documents clearly reference a different country than
  {country_name}) — not because they differ from the US/F-1.
- Use the correct {country_name} vocabulary (e.g. the right visa name, forms, funding proof and
  authorities for {country_name}); never reference US-only items (DS-160, SEVIS, I-20) unless the
  destination is the United States.

Your task:
- First perform critical cross-validation across the raw profile and document files.
- Identify major mismatches, contradictions, or critical missing details first (for example: identity/name mismatch, internal country mismatch within the student's own data, key timeline/date mismatch, university/program mismatch).
- Determine if the user has delayed, missing, invalid, or risky {country_name} student-visa items needing action.
- Consider timeline urgency, mandatory stage documents, invalid document validations, and obvious inconsistencies.
- If any major mismatch exists, treat it as the highest-priority issue before routine reminders.

Return ONLY valid JSON (no markdown/code fences) with EXACTLY these keys:
{{
  "notification_needed": boolean,
  "reasoning": "string (internal log explaining your analysis of the raw files)",
  "email_subject": "string (if needed)",
  "email_body": "string (html formatted friendly reminder)",
  "in_app_message": "string (short text for the bell icon)"
}}

Rules:
- If no action is needed, set notification_needed=false.
- When notification_needed=false: keep email_subject, email_body, in_app_message as empty strings.
- If action is needed, produce clear student-friendly content.
- Keep in_app_message short (max 180 chars).
- When notification_needed=true, email_body must start with a short "Critical checks & cross-verification" section.
- In that section, list major mismatches first. If no major mismatch is found, explicitly state that critical checks are consistent based on currently available data.
- After the critical checks section, include a "Recommended next steps" section in priority order.
- email_body must be valid lightweight HTML and must not include markdown.

RAW STUDENT PROFILE FILE (JSON):
{profile_json_raw}

RAW DOCUMENT EXTRACTED FILES:
{documents_raw_text}
"""


def _analyze_user(model: Any, prompt: str, user_id: int, model_name: str) -> DailyAssistantDecision:
    print("\n" + "=" * 90)
    print(f"🔵 GEMINI REQUEST [daily_ai_notification] user_id={user_id} model={model_name}")
    print("-" * 90)
    print(_clip_for_log(prompt))
    print("=" * 90)

    from app import ai_usage
    response = ai_usage.tracked_gemini_call(
        "daily_ai_notifier", model_name,
        lambda: model.generate_content(prompt, **(
            {} if gemini_utils.USE_VERTEX_AI else {"request_options": {"retry": None}}
        )),
        user_id=user_id, product="b2c", trigger="automation",
        pricing_context=ai_usage.gemini_pricing_context(prompt),
    )
    response_text = str(getattr(response, "text", "") or "")

    print("\n" + "-" * 90)
    print(f"✅ GEMINI RESPONSE [daily_ai_notification] user_id={user_id} model={model_name}")
    print("-" * 90)
    print(_clip_for_log(response_text))
    print("-" * 90 + "\n")

    parsed = _clean_json_response(response_text)
    try:
        return DailyAssistantDecision.model_validate(parsed)
    except ValidationError as exc:
        raise ValueError(f"Gemini JSON schema mismatch: {str(exc)}") from exc


def _load_user_document_payload(user_id: int, db_session, r2_client) -> list[dict]:
    documents = (
        db_session.query(models.Document)
        .filter(
            models.Document.user_id == user_id,
            models.Document.extracted_text_file_url.isnot(None),
        )
        .order_by(models.Document.created_at.asc(), models.Document.id.asc())
        .all()
    )

    payload: list[dict] = []
    for document in documents:
        if not document.extracted_text_file_url:
            continue
        try:
            raw_content = _read_decrypted_r2_text(r2_client, document.extracted_text_file_url)
        except Exception as exc:  # noqa: BLE001
            print(
                f"Daily AI notifier warning: failed to read extracted doc key={document.extracted_text_file_url} "
                f"for user_id={user_id}: {str(exc)}"
            )
            continue

        payload.append(
            {
                "document_type": document.document_type,
                "filename": document.original_filename,
                "is_valid": document.is_valid,
                "validation_message": document.validation_message,
                "content": raw_content,
            }
        )
    return payload


def _load_profile_raw_json(user_id: int, r2_client) -> str:
    key = f"user_{user_id}/{PROFILE_KEY_SUFFIX}"
    return _read_decrypted_r2_text(r2_client, key)


def _process_single_user(user_id: int, model: Any, model_name: str, r2_client) -> bool:
    session = SessionLocal()
    try:
        # Re-check the consumer-only rule here, not just in the run's candidate query: a run
        # walks every due account one Gemini call at a time, so a user who joins a workspace
        # (or is flagged enterprise) after the listing must still be dropped BEFORE the
        # snapshot refresh below writes to R2.
        user = (
            session.query(models.User)
            .filter(
                models.User.id == user_id,
                models.User.is_active.is_(True),
                _consumer_account_clause(),
            )
            .first()
        )
        if not user:
            return False

        try:
            refresh_student_profile_snapshot_for_user(user=user, db=session)
        except Exception as exc:  # noqa: BLE001
            print(f"Daily AI notifier warning: failed profile snapshot refresh for user_id={user_id}: {str(exc)}")

        profile_raw_json = _load_profile_raw_json(user.id, r2_client)
        document_payload = _load_user_document_payload(user.id, session, r2_client)
        prompt = _build_analysis_prompt(user, profile_raw_json, document_payload)
        decision = _analyze_user(model, prompt, user_id=user.id, model_name=model_name)
        print(
            f"Daily AI notifier reasoning user_id={user.id}: "
            f"{_clip_for_log(decision.reasoning)}"
        )

        if not decision.notification_needed:
            print(f"Daily AI notifier: no action needed for user_id={user.id}")
            return False

        jc = _journey_context(user)
        # User-visible AI text — same provider-identity scrub as every chat surface.
        from app.ai_guardrails import sanitize_provider_disclosures
        subject = sanitize_provider_disclosures(
            decision.email_subject or f"Action needed for your {jc['country_name']} study-abroad plan"
        ).strip()[:140]
        in_app_message = sanitize_provider_disclosures(decision.in_app_message or subject).strip()[:180]
        if not in_app_message:
            in_app_message = f"New action item in your {jc['country_name']} study-abroad journey."

        create_user_notification(
            session,
            user_id=user.id,
            title=subject,
            message=in_app_message,
            notification_type="warning",
            source="ai_daily_assistant",
            commit=True,
        )

        if user.email and user.email_notifications_enabled is not False:
            unsubscribe_url = build_email_notifications_unsubscribe_url(email=user.email)
            send_proactive_assistant_email(
                email=user.email,
                full_name=user.full_name,
                subject=subject,
                html_body=sanitize_provider_disclosures(decision.email_body),
                unsubscribe_url=unsubscribe_url,
            )

        print(f"Daily AI notifier: sent proactive notification for user_id={user.id}")
        return True
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        print(f"Daily AI notifier error for user_id={user_id}: {str(exc)}")
        return False
    finally:
        session.close()


def run_daily_ai_notification_job(force: bool = False) -> dict:
    """
    Run one daily proactive notification scan cycle.
    Uses ai_daily_notification_runs.run_date as idempotency guard.
    """
    now_utc = datetime.now(timezone.utc)
    run_date = now_utc.date()

    db = SessionLocal()
    run_row: Optional[models.AIDailyNotificationRun] = None

    try:
        existing_run = (
            db.query(models.AIDailyNotificationRun)
            .filter(models.AIDailyNotificationRun.run_date == run_date)
            .first()
        )
        if existing_run and not force and existing_run.status == "completed":
            return {
                "status": "skipped",
                "reason": "already_ran_for_today",
                "run_date": run_date.isoformat(),
            }
        if (
            existing_run
            and not force
            and existing_run.status == "running"
            and existing_run.started_at
            and (datetime.utcnow() - existing_run.started_at) < timedelta(hours=2)
        ):
            return {
                "status": "skipped",
                "reason": "run_already_in_progress",
                "run_date": run_date.isoformat(),
            }

        if existing_run:
            run_row = existing_run
            run_row.status = "running"
            run_row.started_at = datetime.utcnow()
            run_row.completed_at = None
            run_row.users_scanned = 0
            run_row.notifications_sent = 0
            run_row.error_message = None
            db.commit()
            db.refresh(run_row)
        else:
            run_row = models.AIDailyNotificationRun(
                run_date=run_date,
                status="running",
                started_at=datetime.utcnow(),
                users_scanned=0,
                notifications_sent=0,
            )
            db.add(run_row)
            try:
                db.commit()
                db.refresh(run_row)
            except IntegrityError:
                db.rollback()
                return {
                    "status": "skipped",
                    "reason": "already_ran_for_today",
                    "run_date": run_date.isoformat(),
                }

        model, provider = _build_gemini_model(MODEL_NAME)
        r2_client = _build_r2_client()

        # Enterprise (B2B) accounts are excluded in SQL — see _consumer_account_clause. They
        # are filtered BEFORE the dormancy cadence and the USER_LIMIT slice, so they neither
        # count as "dormant deferred" nor use up a slot a student account should get.
        user_rows = (
            db.query(models.User.id, models.User.created_at, models.User.first_login_at, models.User.last_login_at)
            .filter(models.User.is_active.is_(True), _consumer_account_clause())
            .order_by(models.User.id.asc())
            .all()
        )
        # Reported only (log + result) so the admin "run now" output shows the skip is
        # working; one COUNT, nothing about those accounts is loaded.
        users_skipped_enterprise = int(
            db.query(func.count(models.User.id))
            .filter(models.User.is_active.is_(True), not_(_consumer_account_clause()))
            .scalar()
            or 0
        )
        # Dormant accounts are only scanned on their fortnightly day — see _is_user_due.
        # Applied to forced (admin "run now") runs too: re-running today must not turn
        # into a full re-scan of every dead account.
        user_ids = [int(row.id) for row in user_rows if _is_user_due(row, run_date, now_utc)]
        users_skipped_dormant = len(user_rows) - len(user_ids)
        if DAILY_AI_NOTIFIER_USER_LIMIT > 0:
            user_ids = user_ids[:DAILY_AI_NOTIFIER_USER_LIMIT]
        print(
            f"Daily AI notifier: {len(user_ids)} account(s) due today, "
            f"{users_skipped_dormant} dormant account(s) deferred to their fortnightly scan, "
            f"{users_skipped_enterprise} enterprise account(s) skipped"
        )

        users_scanned = 0
        notifications_sent = 0

        for user_id in user_ids:
            users_scanned += 1
            sent = _process_single_user(user_id=user_id, model=model, model_name=MODEL_NAME, r2_client=r2_client)
            if sent:
                notifications_sent += 1

        run_row.status = "completed"
        run_row.completed_at = datetime.utcnow()
        run_row.users_scanned = users_scanned
        run_row.notifications_sent = notifications_sent
        db.commit()

        return {
            "status": "completed",
            "run_date": run_date.isoformat(),
            "provider": provider,
            "model": MODEL_NAME,
            "users_scanned": users_scanned,
            "users_skipped_dormant": users_skipped_dormant,
            "users_skipped_enterprise": users_skipped_enterprise,
            "notifications_sent": notifications_sent,
        }
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        if run_row:
            try:
                run_row.status = "failed"
                run_row.completed_at = datetime.utcnow()
                run_row.error_message = str(exc)
                db.commit()
            except Exception:  # noqa: BLE001
                db.rollback()
        print(f"Daily AI notifier run failed: {str(exc)}")
        return {
            "status": "failed",
            "run_date": run_date.isoformat(),
            "error": str(exc),
        }
    finally:
        db.close()


_scheduler = DailyAINotificationScheduler()


def start_daily_ai_notification_scheduler() -> None:
    _scheduler.start()


def stop_daily_ai_notification_scheduler() -> None:
    _scheduler.stop()
