"""Enterprise marketplace payments (Razorpay Route) — helper layer.

Rilono acts as a technology platform, NOT a payment aggregator: student money is collected
into *Razorpay's* PA escrow and settled by Razorpay directly to each consultancy's own
verified bank account (a Route "Linked Account"). Rilono only issues split instructions and
retains a commission — it never takes custody of the consultancy's funds.

This module holds the pure fee math, the Razorpay v2 (Accounts/Route) client that surfaces
gateway error descriptions, the linked-account onboarding sequence, and serialization.
Money is integer paise, INR only. All outbound Razorpay calls go through the helpers here so
they can be stubbed in tests. Collection/checkout, webhooks and refunds are separate phases.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime
from typing import Optional

import requests
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app import models

RAZORPAY_API_BASE = os.getenv("RAZORPAY_API_BASE", "https://api.razorpay.com/v1").rstrip("/")
RAZORPAY_API_BASE_V2 = os.getenv("RAZORPAY_API_BASE_V2", "https://api.razorpay.com/v2").rstrip("/")

# --- Fee model: percentage take-rate with a per-transaction minimum floor -----------------
# Rilono's commission = max(amount * percent, floor). Must be set above Razorpay's Route +
# PG + GST costs so it stays net-positive. Env-overridable (no redeploy to re-price).
COMMISSION_PERCENT = float(os.getenv("MARKETPLACE_COMMISSION_PERCENT", "2.0"))
COMMISSION_MIN_PAISE = int(os.getenv("MARKETPLACE_COMMISSION_MIN_PAISE", "4900"))  # ₹49 floor
# Route transfers are INR-only with a 100-paise (₹1) minimum payout.
MIN_PAYOUT_PAISE = 100

# Razorpay Route does NOT support non-INR. This is a platform wall, not a code choice:
#   "You cannot create transfers on orders for international currencies. Currently, this
#    feature only supports orders created using INR."
#   https://razorpay.com/docs/api/payments/route/create-transfers-orders/?preferred-country=IN
#   "We support only INR for Route transactions."
#
# DO NOT parameterise this. The failure mode is the worst one in the product: a non-INR
# order with a transfers[] array is rejected at TRANSFER time, which can be after the
# student has already paid — leaving their money in Rilono's platform account with no
# automated path to the consultancy.
#
# International students are still served: a foreign-issued card can pay an INR-denominated
# order (the `international` flag on the payment is independent of `currency`), and Route
# splits it normally. Only the presentment currency is fixed.
ROUTE_CURRENCY = "INR"


def _razorpay_credentials() -> tuple[str, str]:
    return (os.getenv("RAZORPAY_KEY_ID", "").strip(), os.getenv("RAZORPAY_KEY_SECRET", "").strip())


def razorpay_enabled() -> bool:
    key_id, key_secret = _razorpay_credentials()
    return bool(key_id and key_secret)


def compute_commission(amount_paise: int) -> tuple[int, int]:
    """Return (commission_paise, payout_paise) for a student payment of `amount_paise`.

    Commission is the greater of the percentage take and the floor, capped so the
    consultancy always receives at least the Route minimum. `commission` is Rilono's
    *gross* take (what we retain = amount − payout); Razorpay's Route/PG fees + GST are
    debited separately from Rilono's balance and are NOT baked into the split.
    """
    amount = int(amount_paise or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be greater than zero.")
    pct = int(round(amount * (COMMISSION_PERCENT / 100.0)))
    commission = max(pct, COMMISSION_MIN_PAISE)
    payout = amount - commission
    if payout < MIN_PAYOUT_PAISE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Amount is too small to collect: after the Rilono fee the consultancy would "
                f"receive less than ₹{MIN_PAYOUT_PAISE / 100:.0f}."
            ),
        )
    return commission, payout


def fee_config_public() -> dict:
    """Fee settings surfaced to the portal (for the split preview)."""
    return {
        "percent": COMMISSION_PERCENT,
        "min_fee_rupees": round(COMMISSION_MIN_PAISE / 100.0, 2),
        "currency": "INR",
    }


def split_preview(amount_paise: int) -> dict:
    """A student-facing/consultancy-facing preview of how a payment splits."""
    commission, payout = compute_commission(amount_paise)
    return {
        "amount_paise": int(amount_paise),
        "commission_paise": commission,
        "payout_paise": payout,
    }


# --- Razorpay v2 (Accounts / Route onboarding) client -------------------------------------

def _razorpay_v2_request(method: str, path: str, json_payload: Optional[dict] = None) -> dict:
    """Call the Razorpay v2 API (Accounts/Route). Unlike the v1 helper, this surfaces
    Razorpay's `error.description`/field errors so the onboarding stepper can show the
    consultancy exactly what to fix (bad IFSC, invalid PAN, KYC field errors)."""
    if not razorpay_enabled():
        raise HTTPException(
            status_code=503,
            detail="Online payments aren't enabled yet. This will activate once Rilono turns on Razorpay Route.",
        )
    key_id, key_secret = _razorpay_credentials()
    url = f"{RAZORPAY_API_BASE_V2}/{path.lstrip('/')}"
    try:
        resp = requests.request(method.upper(), url, auth=(key_id, key_secret), json=json_payload, timeout=20)
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="Failed to contact the payment gateway.")
    if resp.status_code >= 400:
        detail = "The payment gateway rejected this onboarding request."
        try:
            err = (resp.json() or {}).get("error") or {}
            if err.get("description"):
                detail = f"Razorpay: {err['description']}"
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=detail)
    try:
        data = resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid response from the payment gateway.")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Unexpected response from the payment gateway.")
    return data


# Map Razorpay's account/product activation states onto our local enum.
_RZP_STATUS_MAP = {
    "created": "created",
    "activated": "activated",
    "needs_clarification": "needs_clarification",
    "under_review": "under_review",
    "suspended": "suspended",
    "requested": "under_review",
}


def _derive_is_payable(activation_status: str) -> bool:
    return activation_status == "activated"


def get_linked_account(db: Session, organization_id: int) -> Optional[models.EnterpriseLinkedAccount]:
    return (
        db.query(models.EnterpriseLinkedAccount)
        .filter(models.EnterpriseLinkedAccount.organization_id == int(organization_id))
        .first()
    )


def _apply_product_state(la: models.EnterpriseLinkedAccount, product: Optional[dict]) -> None:
    """Sync activation_status + requirements + is_payable from a Razorpay product object."""
    product = product or {}
    status = str(product.get("activation_status") or "").strip().lower()
    if status:
        la.activation_status = _RZP_STATUS_MAP.get(status, la.activation_status)
    reqs = product.get("requirements")
    if reqs is not None:
        try:
            la.requirements_json = json.dumps(reqs)[:20000]
        except Exception:
            pass
    la.is_payable = _derive_is_payable(la.activation_status)


def onboard_linked_account(*, db: Session, linked_account: models.EnterpriseLinkedAccount, payload, request_ip: Optional[str] = None) -> models.EnterpriseLinkedAccount:
    """Run the Razorpay Route v2 onboarding sequence (create account -> stakeholder ->
    route product -> settlement bank account). Resumable: each step is skipped if already
    done, so re-submitting continues from where it left off. Only called when Route is live.
    """
    la = linked_account
    account_id = la.razorpay_account_id

    # 1. Create the sub-merchant account.
    if not account_id:
        acc = _razorpay_v2_request("POST", "/accounts", {
            "email": (payload.contact_email or "").strip(),
            "phone": re.sub(r"\D", "", (payload.contact_phone or "")) or None,
            "type": "route",
            "legal_business_name": (payload.legal_business_name or "").strip(),
            "business_type": ((payload.business_type or "").strip().lower() or None),
            "contact_name": (payload.contact_name or "").strip(),
            "profile": {"category": "education", "subcategory": "consulting_services"},
            "legal_info": {
                k: v for k, v in {
                    "pan": (payload.business_pan or "").strip().upper() or None,
                    "gst": (payload.gst_number or "").strip().upper() or None,
                }.items() if v
            },
        })
        account_id = acc.get("id")
        la.razorpay_account_id = account_id
        la.activation_status = "created"
        db.flush()

    # 2. Add the owner/stakeholder (KYC lives with Razorpay, not Rilono).
    if account_id and not la.razorpay_stakeholder_id and (payload.contact_name or "").strip():
        sth = _razorpay_v2_request("POST", f"/accounts/{account_id}/stakeholders", {
            "name": (payload.contact_name or "").strip(),
            "email": (payload.contact_email or "").strip(),
        })
        la.razorpay_stakeholder_id = sth.get("id")
        la.activation_status = "stakeholder_added"
        db.flush()

    # 3. Request the Route product config.
    if account_id and not la.razorpay_product_id:
        prod = _razorpay_v2_request("POST", f"/accounts/{account_id}/products", {
            "product_name": "route",
            "tnc_accepted": True,
        })
        la.razorpay_product_id = prod.get("id")
        la.activation_status = "product_requested"
        _apply_product_state(la, prod)
        db.flush()

    # 4. Submit the settlement bank account.
    acct_digits = re.sub(r"\D", "", (payload.bank_account_number or ""))
    if account_id and la.razorpay_product_id and acct_digits and (payload.bank_ifsc or "").strip():
        settlement_payload = {
            "settlements": {
                "account_number": acct_digits,
                "ifsc_code": (payload.bank_ifsc or "").strip().upper(),
                "beneficiary_name": (payload.beneficiary_name or payload.legal_business_name or "").strip(),
            },
            "tnc_accepted": True,
        }
        if request_ip:
            settlement_payload["ip"] = request_ip
        prod = _razorpay_v2_request(
            "PATCH", f"/accounts/{account_id}/products/{la.razorpay_product_id}", settlement_payload
        )
        if la.activation_status in ("product_requested", "stakeholder_added", "created"):
            la.activation_status = "settlement_submitted"
        _apply_product_state(la, prod)
        db.flush()

    return la


def refresh_linked_account_status(*, db: Session, linked_account: models.EnterpriseLinkedAccount) -> models.EnterpriseLinkedAccount:
    """Re-fetch the Route product config and sync activation_status/requirements/is_payable."""
    la = linked_account
    if not la.razorpay_account_id or not la.razorpay_product_id:
        raise HTTPException(status_code=404, detail="No connected account to refresh.")
    prod = _razorpay_v2_request("GET", f"/accounts/{la.razorpay_account_id}/products/{la.razorpay_product_id}")
    _apply_product_state(la, prod)
    db.flush()
    return la


# ==========================================================================================
# Phase 2 — collection: payment requests, secure pay-link, webhook reconciliation, refunds
# ==========================================================================================

# Sanity cap per payment request (env-tunable; Razorpay/bank instrument caps also apply).
MAX_AMOUNT_PAISE = int(os.getenv("MARKETPLACE_MAX_AMOUNT_PAISE", str(5_00_000 * 100)))  # ₹5,00,000

# Monotonic progression guard so out-of-order webhooks never move a payment backwards.
_STATUS_RANK = {"created": 0, "failed": 0, "paid": 1, "transferred": 2, "settled": 3}


def _razorpay_v1_request(method: str, path: str, json_payload: Optional[dict] = None) -> dict:
    """Call the Razorpay v1 API (orders / payments / refunds) surfacing `error.description`
    (unlike the older opaque helper) — a failed refund or order must tell staff why."""
    if not razorpay_enabled():
        raise HTTPException(
            status_code=503,
            detail="Online payments aren't enabled yet. This will activate once Rilono turns on Razorpay Route.",
        )
    key_id, key_secret = _razorpay_credentials()
    url = f"{RAZORPAY_API_BASE}/{path.lstrip('/')}"
    try:
        resp = requests.request(method.upper(), url, auth=(key_id, key_secret), json=json_payload, timeout=20)
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="Failed to contact the payment gateway.")
    if resp.status_code >= 400:
        detail = "The payment gateway rejected this request."
        try:
            err = (resp.json() or {}).get("error") or {}
            if err.get("description"):
                detail = f"Razorpay: {err['description']}"
        except Exception:
            pass
        raise HTTPException(status_code=400, detail=detail)
    try:
        data = resp.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Invalid response from the payment gateway.")
    if not isinstance(data, dict):
        raise HTTPException(status_code=502, detail="Unexpected response from the payment gateway.")
    return data


def create_payment_request(
    *,
    db: Session,
    organization: models.EnterpriseOrganization,
    linked_account: models.EnterpriseLinkedAccount,
    client: models.EnterpriseClient,
    amount_paise: int,
    description: str,
    due_date=None,
    created_by: models.User,
    pay_token_hash: str,
    payer_email: Optional[str] = None,
    payer_phone: Optional[str] = None,
    currency: Optional[str] = None,
) -> models.EnterpriseStudentPayment:
    """Create a student payment request + the Razorpay Route order (inline transfer split).

    Compliance guardrails enforced here:
      * the linked account must be `is_payable` (activated) — a marketplace must never
        collect for a non-onboarded payee;
      * INR only; split asserted `commission + payout == amount` with payout >= ₹1;
      * the consultancy's share goes straight to THEIR linked account (Razorpay escrow ->
        their bank) — Rilono retains only the commission.
    """
    if not linked_account or not linked_account.is_payable or not linked_account.razorpay_account_id:
        raise HTTPException(
            status_code=409,
            detail="Connect and activate your company bank account in Finance before collecting payments.",
        )
    amount = int(amount_paise or 0)
    if amount > MAX_AMOUNT_PAISE:
        raise HTTPException(
            status_code=400,
            detail=f"Amount exceeds the per-payment limit of ₹{MAX_AMOUNT_PAISE / 100:,.0f}.",
        )
    # Belt-and-braces against a future caller threading a currency through here: Route
    # would accept the order and then fail the transfer, stranding the student's money.
    if currency is not None and str(currency).strip().upper() != ROUTE_CURRENCY:
        raise HTTPException(
            status_code=400,
            detail=(
                "Student payments can only be collected in INR. International students can "
                "still pay this invoice with an overseas card."
            ),
        )
    commission, payout = compute_commission(amount)
    assert commission + payout == amount and payout >= MIN_PAYOUT_PAISE

    payment = models.EnterpriseStudentPayment(
        organization_id=organization.id,
        client_id=client.id,
        client_name_snapshot=client.full_name,
        linked_account_id=linked_account.id,
        description=(description or "").strip()[:300] or None,
        amount_paise=amount,
        commission_paise=commission,
        payout_paise=payout,
        currency=ROUTE_CURRENCY,
        provider="razorpay",
        status="created",
        due_date=due_date,
        created_by_user_id=created_by.id,
        pay_token_hash=pay_token_hash,
        payer_email_snapshot=(payer_email or "").strip().lower() or None,
        # Razorpay: "Your international payment will fail if you send us a dummy email id
        # and phone number of the customer." Snapshot the student's real phone at request
        # time so the pay page can prefill it — without it every foreign card fails here.
        payer_phone_snapshot=(payer_phone or "").strip() or None,
    )
    db.add(payment)
    db.flush()  # get payment.id for notes + invoice number
    payment.invoice_number = f"INV-{organization.id}-{payment.id:06d}"

    order = _razorpay_v1_request("POST", "/orders", {
        "amount": amount,
        "currency": ROUTE_CURRENCY,
        "receipt": f"spr_{organization.id}_{payment.id}",
        "payment_capture": 1,
        "notes": {"spr_id": str(payment.id), "organization_id": str(organization.id)},
        "transfers": [{
            "account": linked_account.razorpay_account_id,
            "amount": payout,
            "currency": ROUTE_CURRENCY,
            "notes": {"spr_id": str(payment.id)},
            "linked_account_notes": ["spr_id"],
            "on_hold": False,  # pass-through: settles on Razorpay's normal schedule
        }],
    })
    payment.razorpay_order_id = order.get("id")
    db.flush()
    return payment


# Off-platform payment methods staff can record. Keys are stored; labels are for display.
MANUAL_PAYMENT_METHODS: dict[str, str] = {
    "cash": "Cash",
    "bank_transfer": "Bank transfer",
    "upi": "UPI",
    "card": "Card / POS",
    "cheque": "Cheque",
    "other": "Other",
}


def normalize_manual_method(method: Optional[str]) -> Optional[str]:
    key = (method or "").strip().lower().replace(" ", "_")
    return key if key in MANUAL_PAYMENT_METHODS else None


def record_manual_payment(
    *,
    db: Session,
    organization: models.EnterpriseOrganization,
    client: models.EnterpriseClient,
    amount_paise: int,
    method: str,
    description: Optional[str] = None,
    reference: Optional[str] = None,
    received_on=None,
    created_by: models.User,
) -> models.EnterpriseStudentPayment:
    """Record a payment the consultancy collected OUTSIDE Rilono (cash / bank transfer / UPI / …).

    This is a bookkeeping entry only — no money moves through the platform, so there is no
    Razorpay order, Rilono takes NO commission (the full amount is the consultancy's), and it
    needs no linked account (works even before online collection is activated). It lands as an
    immediately-'paid' row so it counts toward the client's Collected total next to online ones.
    """
    amount = int(amount_paise or 0)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Enter the amount received.")
    if amount > MAX_AMOUNT_PAISE:
        raise HTTPException(
            status_code=400,
            detail=f"Amount exceeds the per-payment limit of ₹{MAX_AMOUNT_PAISE / 100:,.0f}.",
        )
    method_key = normalize_manual_method(method)
    if not method_key:
        raise HTTPException(status_code=400, detail="Choose a valid payment method.")

    if received_on is not None:
        from datetime import time as _time
        paid_at = datetime.combine(received_on, _time.min)
    else:
        paid_at = datetime.utcnow()

    payment = models.EnterpriseStudentPayment(
        organization_id=organization.id,
        client_id=client.id,
        client_name_snapshot=client.full_name,
        linked_account_id=None,
        description=(description or "").strip()[:300] or None,
        amount_paise=amount,
        commission_paise=0,        # Rilono earns nothing on money it never touched
        payout_paise=amount,       # the full amount is the consultancy's
        currency="INR",
        provider="manual",
        manual_method=method_key,
        status="paid",             # already collected → counts toward the Collected total
        utr=(reference or "").strip()[:80] or None,
        paid_at=paid_at,
        created_by_user_id=created_by.id,
    )
    db.add(payment)
    db.flush()  # get id for the reference number
    payment.invoice_number = f"MAN-{organization.id}-{payment.id:06d}"
    db.flush()
    return payment


def client_payment_totals(db: Session, organization_id: int, client_id: int) -> dict:
    """Aggregate money view for one client's dossier (integer paise)."""
    rows = (
        db.query(models.EnterpriseStudentPayment)
        .filter(
            models.EnterpriseStudentPayment.organization_id == int(organization_id),
            models.EnterpriseStudentPayment.client_id == int(client_id),
        )
        .all()
    )
    collected = sum(p.amount_paise for p in rows if p.status in ("paid", "transferred", "settled", "partially_refunded"))
    pending = sum(p.amount_paise for p in rows if p.status == "created")
    refunded = sum(int(p.refunded_amount_paise or 0) for p in rows)
    return {
        "collected_paise": collected,
        "pending_paise": pending,
        "refunded_paise": refunded,
        "count": len(rows),
    }


def serialize_payment(p: models.EnterpriseStudentPayment) -> dict:
    return {
        "id": p.id,
        "client_id": p.client_id,
        "client_name": p.client_name_snapshot,
        "invoice_number": p.invoice_number,
        "description": p.description,
        "amount_paise": p.amount_paise,
        "commission_paise": p.commission_paise,
        "payout_paise": p.payout_paise,
        "currency": p.currency,
        "provider": p.provider,
        "is_manual": (p.provider == "manual"),
        "manual_method": getattr(p, "manual_method", None),
        "status": p.status,
        "settlement_status": p.settlement_status,
        "refunded_amount_paise": int(p.refunded_amount_paise or 0),
        "utr": p.utr,
        "dispute_status": p.dispute_status,
        "disputed_at": p.disputed_at.isoformat() if p.disputed_at else None,
        "due_date": p.due_date.isoformat() if p.due_date else None,
        "payer_email": p.payer_email_snapshot,
        "email_sent_at": p.email_sent_at.isoformat() if p.email_sent_at else None,
        "paid_at": p.paid_at.isoformat() if p.paid_at else None,
        "settled_at": p.settled_at.isoformat() if p.settled_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def verify_checkout_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """Standard Razorpay checkout verification: HMAC-SHA256(order_id|payment_id, key_secret)."""
    import hashlib
    import hmac as _hmac
    _, key_secret = _razorpay_credentials()
    if not (key_secret and order_id and payment_id and signature):
        return False
    expected = _hmac.new(key_secret.encode(), f"{order_id}|{payment_id}".encode(), hashlib.sha256).hexdigest()
    return _hmac.compare_digest(expected, signature)


def confirm_captured_and_mark_paid(
    *, db: Session, payment: models.EnterpriseStudentPayment, razorpay_payment_id: str
) -> models.EnterpriseStudentPayment:
    """After a signature-verified checkout callback, confirm CAPTURE with the Razorpay API
    (the signature alone proves authenticity, not capture) and mark the request paid."""
    detail = _razorpay_v1_request("GET", f"/payments/{razorpay_payment_id}")
    if str(detail.get("status") or "").lower() != "captured":
        raise HTTPException(status_code=409, detail="Payment is not captured yet. It will reflect automatically once confirmed.")
    if int(detail.get("amount") or 0) != int(payment.amount_paise):
        raise HTTPException(status_code=400, detail="Payment amount mismatch.")
    payment.razorpay_payment_id = razorpay_payment_id
    if _STATUS_RANK.get(payment.status, 0) < _STATUS_RANK["paid"]:
        payment.status = "paid"
    payment.paid_at = payment.paid_at or datetime.utcnow()
    db.flush()
    return payment


# --- Webhook reconciliation (source of truth; idempotent + out-of-order tolerant) ---------

def record_webhook_event(db: Session, *, event_id: Optional[str], event_type: str,
                         entity_type: str, entity_id: Optional[str],
                         amount_paise: Optional[int], payload_json: str,
                         organization_id: Optional[int], student_payment_id: Optional[int]) -> bool:
    """Insert the event row; returns False when this event_id was already processed
    (the UNIQUE constraint on razorpay_event_id is the real dedupe guard)."""
    from sqlalchemy.exc import IntegrityError
    evt = models.EnterprisePaymentEvent(
        organization_id=organization_id,
        student_payment_id=student_payment_id,
        razorpay_event_id=(event_id or None),
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        amount_paise=amount_paise,
        payload_json=payload_json[:20000],
        processed_at=datetime.utcnow(),
    )
    db.add(evt)
    try:
        db.flush()
        return True
    except IntegrityError:
        db.rollback()
        return False


def _find_payment_for_event(db: Session, entity: dict) -> Optional[models.EnterpriseStudentPayment]:
    """Locate the payment row for a webhook entity — notes.spr_id first (order-independent),
    then order/payment ids."""
    notes = entity.get("notes") or {}
    spr_id = notes.get("spr_id") if isinstance(notes, dict) else None
    if spr_id and str(spr_id).isdigit():
        row = db.query(models.EnterpriseStudentPayment).filter(
            models.EnterpriseStudentPayment.id == int(spr_id)
        ).first()
        if row:
            return row
    order_id = entity.get("order_id") or (entity.get("id") if str(entity.get("id") or "").startswith("order_") else None)
    if order_id:
        row = db.query(models.EnterpriseStudentPayment).filter(
            models.EnterpriseStudentPayment.razorpay_order_id == order_id
        ).first()
        if row:
            return row
    pay_id = entity.get("payment_id") or entity.get("source") or (
        entity.get("id") if str(entity.get("id") or "").startswith("pay_") else None
    )
    if pay_id and str(pay_id).startswith("pay_"):
        return db.query(models.EnterpriseStudentPayment).filter(
            models.EnterpriseStudentPayment.razorpay_payment_id == pay_id
        ).first()
    return None


def apply_webhook_event(db: Session, event_type: str, payload: dict) -> Optional[models.EnterpriseStudentPayment]:
    """Apply one Route webhook event to the payment state machine. Idempotent: guarded by
    the monotonic status rank, so replays and out-of-order delivery are safe."""
    container = (payload or {}).get("payload") or {}

    def _entity(kind: str) -> dict:
        return ((container.get(kind) or {}).get("entity")) or {}

    if event_type in ("payment.captured", "order.paid"):
        entity = _entity("payment") or _entity("order")
        payment = _find_payment_for_event(db, entity)
        if not payment:
            return None
        pay_id = entity.get("id") if str(entity.get("id") or "").startswith("pay_") else entity.get("payment_id")
        if pay_id and not payment.razorpay_payment_id:
            payment.razorpay_payment_id = pay_id
        if _STATUS_RANK.get(payment.status, 0) < _STATUS_RANK["paid"] and payment.status != "cancelled":
            payment.status = "paid"
        payment.paid_at = payment.paid_at or datetime.utcnow()
        db.flush()
        return payment

    if event_type == "payment.failed":
        entity = _entity("payment")
        payment = _find_payment_for_event(db, entity)
        if payment and payment.status == "created":
            payment.status = "failed"
            db.flush()
        return payment

    if event_type in ("transfer.processed", "transfer.settled"):
        entity = _entity("transfer")
        payment = _find_payment_for_event(db, entity)
        if not payment:
            return None
        if str(entity.get("id") or "").startswith("trf_"):
            payment.razorpay_transfer_id = entity.get("id")
        payment.settlement_status = entity.get("settlement_status") or payment.settlement_status
        target = "settled" if event_type == "transfer.settled" else "transferred"
        if _STATUS_RANK.get(payment.status, 0) < _STATUS_RANK[target] and payment.status != "cancelled":
            payment.status = target
        if event_type == "transfer.settled":
            payment.settled_at = payment.settled_at or datetime.utcnow()
            payment.utr = entity.get("utr") or payment.utr
        db.flush()
        return payment

    if event_type == "refund.processed":
        entity = _entity("refund")
        payment = _find_payment_for_event(db, entity)
        if not payment:
            return None
        amount = int(entity.get("amount") or 0)
        already = int(payment.refunded_amount_paise or 0)
        # Guard replays: never exceed the collected amount.
        payment.refunded_amount_paise = min(already + amount, payment.amount_paise) if amount else already
        payment.status = "refunded" if payment.refunded_amount_paise >= payment.amount_paise else "partially_refunded"
        refund_id = entity.get("id")
        if refund_id:
            audit = db.query(models.EnterprisePaymentRefund).filter(
                models.EnterprisePaymentRefund.razorpay_refund_id == refund_id
            ).first()
            if audit and audit.status != "processed":
                audit.status = "processed"
        db.flush()
        return payment

    if event_type.startswith("payment.dispute."):
        # Chargeback/dispute lifecycle. Liability sits with the consultancy (Terms §6.7);
        # we track state + deadline so staff can respond in the Razorpay dashboard.
        entity = _entity("dispute")
        payment = _find_payment_for_event(db, entity)
        suffix = event_type.rsplit(".", 1)[-1]
        status_map = {
            "created": "open",
            "under_review": "under_review",
            "action_required": "action_required",
            "won": "won",
            "lost": "lost",
            "closed": "closed",
        }
        new_status = status_map.get(suffix) or str(entity.get("status") or "open")

        respond_by = None
        try:
            if entity.get("respond_by"):
                respond_by = datetime.utcfromtimestamp(int(entity["respond_by"]))
        except (TypeError, ValueError, OSError, OverflowError):
            respond_by = None

        dispute_id = str(entity.get("id") or "") or None
        audit = None
        if dispute_id:
            audit = db.query(models.EnterprisePaymentDispute).filter(
                models.EnterprisePaymentDispute.razorpay_dispute_id == dispute_id
            ).first()
        if audit is None:
            audit = models.EnterprisePaymentDispute(
                organization_id=payment.organization_id if payment else None,
                student_payment_id=payment.id if payment else None,
                razorpay_dispute_id=dispute_id,
            )
            db.add(audit)
        audit.razorpay_payment_id = str(entity.get("payment_id") or "") or audit.razorpay_payment_id
        audit.amount_paise = int(entity.get("amount") or audit.amount_paise or 0)
        audit.currency = str(entity.get("currency") or audit.currency or "INR")
        audit.phase = str(entity.get("phase") or "") or audit.phase
        audit.reason_code = str(entity.get("reason_code") or "") or audit.reason_code
        audit.respond_by = respond_by or audit.respond_by
        audit.status = new_status
        if new_status in ("won", "lost", "closed") and audit.resolved_at is None:
            audit.resolved_at = datetime.utcnow()

        if payment:
            payment.dispute_status = new_status
            payment.disputed_at = payment.disputed_at or datetime.utcnow()
            # Money movement on a lost dispute arrives via its own refund/adjustment
            # webhooks; here we only track the dispute lifecycle.
        db.flush()
        return payment

    return None


def issue_full_refund(
    *, db: Session, payment: models.EnterpriseStudentPayment,
    by_user: models.User, reason: Optional[str] = None,
) -> models.EnterprisePaymentRefund:
    """Refund the student in full. Gateway-first, persist-second: `reverse_all=1` claws the
    consultancy's share back from their linked account, then the student is refunded to the
    ORIGINAL instrument (never a different account). Fails cleanly (DB untouched) if the
    gateway rejects it — e.g. the transfer has already settled."""
    if payment.status not in ("paid", "transferred", "settled", "partially_refunded"):
        raise HTTPException(status_code=409, detail="Only a collected payment can be refunded.")
    if not payment.razorpay_payment_id:
        raise HTTPException(status_code=409, detail="No captured payment found for this request.")
    remaining = payment.amount_paise - int(payment.refunded_amount_paise or 0)
    if remaining <= 0:
        raise HTTPException(status_code=409, detail="This payment is already fully refunded.")

    refund = _razorpay_v1_request(
        "POST", f"/payments/{payment.razorpay_payment_id}/refund",
        {"amount": remaining, "reverse_all": 1, "notes": {"spr_id": str(payment.id)}},
    )

    payment.refunded_amount_paise = payment.amount_paise
    payment.status = "refunded"
    audit = models.EnterprisePaymentRefund(
        organization_id=payment.organization_id,
        student_payment_id=payment.id,
        kind="money",
        amount_paise=remaining,
        currency="INR",
        provider="razorpay",
        razorpay_refund_id=refund.get("id"),
        reverse_all=True,
        status=str(refund.get("status") or "created"),
        reason=(reason or "").strip() or None,
        created_by_user_id=by_user.id,
        created_by_name=by_user.full_name or by_user.email,
    )
    db.add(audit)
    db.flush()
    return audit


def serialize_linked_account(
    la: Optional[models.EnterpriseLinkedAccount], *, include_sensitive: bool = True
) -> Optional[dict]:
    """Serialize the linked account. Settlement identity fields (bank IFSC + last4,
    beneficiary, GST, the Razorpay account id) are only included when include_sensitive=True —
    callers must pass False for non-admin viewers so a read-only member can't read the
    consultancy's settlement details (least privilege)."""
    if la is None:
        return None
    requirements = []
    if la.requirements_json:
        try:
            requirements = json.loads(la.requirements_json)
        except Exception:
            requirements = []
    data = {
        "id": la.id,
        "activation_status": la.activation_status,
        "is_payable": bool(la.is_payable),
        "legal_business_name": la.legal_business_name,
        "business_type": la.business_type,
        "contact_name": la.contact_name,
        "contact_email": la.contact_email,
        "requirements": requirements,
        "attested": bool(la.attested_service_delivery and la.attested_turnover_ok),
        "created_at": la.created_at.isoformat() if la.created_at else None,
        "updated_at": la.updated_at.isoformat() if la.updated_at else None,
    }
    if include_sensitive:
        data.update({
            "gst_number": la.gst_number,
            "bank_account_last4": la.bank_account_last4,
            "bank_ifsc": la.bank_ifsc,
            "beneficiary_name": la.beneficiary_name,
            "razorpay_account_id": la.razorpay_account_id,
        })
    return data
