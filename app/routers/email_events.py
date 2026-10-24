"""Resend delivery-event webhook -> per-user "email undeliverable" flag.

Resend dashboard -> Webhooks -> add an endpoint for
    https://<host>/api/webhooks/resend/email-events
subscribed to email.bounced, email.complained, email.suppressed, suppression.added and
suppression.removed, and put its signing secret in RESEND_DELIVERABILITY_WEBHOOK_SECRET.
Policy and state live in app/email_deliverability.py.
"""

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app import email_deliverability
from app.database import get_db
from app.enterprise_inbound_email import verify_svix_signature
from app.utils.rate_limiter import check_ip_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["webhooks"])

# Delivery events are small JSON documents (no message bodies).
_MAX_BODY_BYTES = 256_000


@router.post("/resend/email-events")
async def resend_email_events_webhook(request: Request, db: Session = Depends(get_db)):
    """Receive Resend delivery events (Svix-signed over the RAW body) and record or clear
    the recipient's undeliverable flag. Unknown event types and addresses that match no
    account return 200 so the provider doesn't retry them; a failure while recording
    returns 500 so it does."""
    # A broadcast to a stale list can bounce in bursts; a 429 is retried by Svix anyway.
    allowed, retry_after = check_ip_rate_limit(
        request=request, scope="webhooks.resend_email_events", limit=600, window_seconds=60,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    secret = email_deliverability.webhook_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="Webhook not configured.")
    try:
        declared_length = int(request.headers.get("content-length") or 0)
    except ValueError:
        declared_length = 0
    if declared_length > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large.")
    body = await request.body()
    if len(body) > _MAX_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large.")
    if not verify_svix_signature(secret=secret, headers=request.headers, body=body):
        raise HTTPException(status_code=400, detail="Invalid webhook signature.")

    try:
        event = json.loads(body.decode("utf-8"))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")
    if not isinstance(event, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook payload.")

    try:
        return email_deliverability.apply_event(db, event)
    except Exception:
        db.rollback()
        logger.exception("resend email-events webhook: failed to apply %s", event.get("type"))
        raise HTTPException(status_code=500, detail="Could not record the event.")
