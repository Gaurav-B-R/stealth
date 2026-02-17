import json
import os
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import boto3
from botocore.config import Config
from pydantic import BaseModel, ValidationError
from sqlalchemy.exc import IntegrityError

from app import models
from app.database import SessionLocal
from app.email_service import send_proactive_assistant_email
from app.notification_center import create_user_notification
from app.routers.documents import refresh_student_profile_snapshot_for_user
from app.utils import gemini_service as gemini_utils
from app.utils.secure_artifacts import decrypt_artifact_bytes

MODEL_NAME = "gemini-3-pro-preview"
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


def _build_gemini_model():
    if gemini_utils.USE_VERTEX_AI and gemini_utils.VERTEX_AI_AVAILABLE:
        from vertexai.generative_models import GenerativeModel

        return GenerativeModel(MODEL_NAME), "vertex"

    if gemini_utils.GENAI_AVAILABLE and gemini_utils.genai:
        return gemini_utils.genai.GenerativeModel(MODEL_NAME), "genai"

    raise RuntimeError("Gemini is not configured (service account or API key missing)")


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


def _build_analysis_prompt(user: models.User, profile_json_raw: str, document_payload: list[dict]) -> str:
    now_iso = datetime.now(timezone.utc).isoformat()
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

    return f"""You are Rilono's proactive AI F1 Visa assistant.
Analyze the user's full raw profile JSON and raw extracted document files.

Current UTC datetime: {now_iso}
User context:
- user_id: {user.id}
- full_name: {user.full_name or ''}
- email: {user.email}
- current_residence_country: {getattr(user, 'current_residence_country', None) or ''}

Your task:
- Cross-reference all raw files.
- Determine if the user has delayed, missing, invalid, or risky F1-visa-related items needing action.
- Consider timeline urgency, mandatory stage documents, invalid document validations, and obvious inconsistencies.

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
- email_body must be valid lightweight HTML and must not include markdown.

RAW STUDENT PROFILE FILE (JSON):
{profile_json_raw}

RAW DOCUMENT EXTRACTED FILES:
{documents_raw_text}
"""


def _analyze_user(model: Any, prompt: str, user_id: int) -> DailyAssistantDecision:
    print("\n" + "=" * 90)
    print(f"🔵 GEMINI REQUEST [daily_ai_notification] user_id={user_id} model={MODEL_NAME}")
    print("-" * 90)
    print(_clip_for_log(prompt))
    print("=" * 90)

    response = model.generate_content(prompt)
    response_text = str(getattr(response, "text", "") or "")

    print("\n" + "-" * 90)
    print(f"✅ GEMINI RESPONSE [daily_ai_notification] user_id={user_id} model={MODEL_NAME}")
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


def _process_single_user(user_id: int, model: Any, r2_client) -> bool:
    session = SessionLocal()
    try:
        user = (
            session.query(models.User)
            .filter(models.User.id == user_id, models.User.is_active.is_(True))
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
        decision = _analyze_user(model, prompt, user_id=user.id)
        print(
            f"Daily AI notifier reasoning user_id={user.id}: "
            f"{_clip_for_log(decision.reasoning)}"
        )

        if not decision.notification_needed:
            print(f"Daily AI notifier: no action needed for user_id={user.id}")
            return False

        subject = (decision.email_subject or "Action needed for your F1 visa plan").strip()[:140]
        in_app_message = (decision.in_app_message or subject).strip()[:180]
        if not in_app_message:
            in_app_message = "New action item in your F1 visa journey."

        create_user_notification(
            session,
            user_id=user.id,
            title=subject,
            message=in_app_message,
            notification_type="warning",
            source="ai_daily_assistant",
            commit=True,
        )

        if user.email:
            send_proactive_assistant_email(
                email=user.email,
                full_name=user.full_name,
                subject=subject,
                html_body=decision.email_body,
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

        model, provider = _build_gemini_model()
        r2_client = _build_r2_client()

        user_id_rows = (
            db.query(models.User.id)
            .filter(models.User.is_active.is_(True))
            .order_by(models.User.id.asc())
            .all()
        )
        user_ids = [int(row[0]) for row in user_id_rows]
        if DAILY_AI_NOTIFIER_USER_LIMIT > 0:
            user_ids = user_ids[:DAILY_AI_NOTIFIER_USER_LIMIT]

        users_scanned = 0
        notifications_sent = 0

        for user_id in user_ids:
            users_scanned += 1
            sent = _process_single_user(user_id=user_id, model=model, r2_client=r2_client)
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
