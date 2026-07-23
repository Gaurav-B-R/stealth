"""
Enterprise inbound email — client replies threaded back into the CRM.

Outbound client emails set a tokenized Reply-To like

    reply+c123-9f8a7b6c5d4e3f21@inbound.rilono.com

where the token HMAC-signs the client id. Resend Inbound receives mail on that
subdomain and POSTs a Svix-signed `email.received` webhook to
/api/enterprise/webhooks/inbound-email, which resolves the token back to the
client and logs the reply as an inbound EnterpriseClientEmail row.

Feature-flagged by env: everything degrades to today's behavior (Reply-To =
the staff member's own email) until BOTH are configured:

    RESEND_INBOUND_REPLY_DOMAIN    e.g. "inbound.rilono.com" (MX -> Resend)
    RESEND_INBOUND_WEBHOOK_SECRET  the Svix signing secret ("whsec_...") from
                                   the Resend webhook for `email.received`

SECRET_KEY (the app's existing signing key) is used for the reply tokens.
"""

import base64
import hashlib
import hmac
import html as html_lib
import logging
import os
import re
import time
from typing import Iterable, Mapping, Optional

logger = logging.getLogger(__name__)

# Svix allows 5 minutes of clock skew on webhook timestamps.
_SVIX_TOLERANCE_SECONDS = 5 * 60

_ADDRESS_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_REPLY_LOCAL_RE = re.compile(r"^reply\+c(\d{1,12})-([0-9a-f]{16})$", re.IGNORECASE)


def _secret_key() -> str:
    return (os.getenv("SECRET_KEY") or "").strip()


def reply_domain() -> str:
    return (os.getenv("RESEND_INBOUND_REPLY_DOMAIN") or "").strip().lower().strip("@")


def webhook_secret() -> str:
    return (os.getenv("RESEND_INBOUND_WEBHOOK_SECRET") or "").strip()


def reply_routing_enabled() -> bool:
    """True when outbound client emails should carry a tokenized Reply-To."""
    return bool(reply_domain() and _secret_key())


def _client_token_signature(client_id: int) -> str:
    key = _secret_key()
    if not key:
        return ""
    message = f"ent-client-reply:{int(client_id)}".encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()[:16]


def reply_address_for_client(client_id: int) -> Optional[str]:
    """Deterministic per-client reply address, or None when not configured."""
    domain = reply_domain()
    sig = _client_token_signature(client_id)
    if not domain or not sig:
        return None
    return f"reply+c{int(client_id)}-{sig}@{domain}"


def parse_reply_address(address: str) -> Optional[int]:
    """Return the client id encoded in a reply+ address, or None if it isn't
    ours / the signature doesn't verify."""
    domain = reply_domain()
    if not domain or not address or "@" not in address:
        return None
    local, _, addr_domain = address.strip().lower().rpartition("@")
    if addr_domain != domain:
        return None
    match = _REPLY_LOCAL_RE.match(local)
    if not match:
        return None
    client_id = int(match.group(1))
    expected = _client_token_signature(client_id)
    if not expected or not hmac.compare_digest(expected, match.group(2)):
        return None
    return client_id


# ---------------------------------------------------------------------------
# Svix webhook signature (Resend signs webhooks with Svix)
# ---------------------------------------------------------------------------

def verify_svix_signature(*, secret: str, headers: Mapping[str, str], body: bytes) -> bool:
    """Verify a Svix-signed webhook: HMAC-SHA256 over "{id}.{timestamp}.{body}"
    with the base64 part of the "whsec_..." secret; header carries one or more
    space-separated "v1,<base64sig>" candidates."""
    msg_id = (headers.get("svix-id") or "").strip()
    timestamp = (headers.get("svix-timestamp") or "").strip()
    signatures = (headers.get("svix-signature") or "").strip()
    if not msg_id or not timestamp or not signatures:
        return False
    try:
        if abs(time.time() - int(timestamp)) > _SVIX_TOLERANCE_SECONDS:
            return False
    except (TypeError, ValueError):
        return False
    raw_secret = secret.strip()
    if raw_secret.startswith("whsec_"):
        raw_secret = raw_secret[len("whsec_"):]
    try:
        key = base64.b64decode(raw_secret, validate=True)
    except Exception:
        return False
    signed_content = f"{msg_id}.{timestamp}.".encode() + body
    expected = base64.b64encode(hmac.new(key, signed_content, hashlib.sha256).digest()).decode()
    for candidate in signatures.split(" "):
        candidate = candidate.strip()
        if "," in candidate:
            version, _, sig = candidate.partition(",")
            if version.strip() == "v1" and hmac.compare_digest(expected, sig.strip()):
                return True
    return False


# ---------------------------------------------------------------------------
# Payload parsing helpers
# ---------------------------------------------------------------------------

def _addresses_from_value(value) -> list[str]:
    """Pull bare lowercase email addresses out of whatever shape the provider
    sends: "a@b", "Name <a@b>", {"email": ...}, or lists of those."""
    found: list[str] = []
    if value is None:
        return found
    if isinstance(value, dict):
        value = value.get("email") or value.get("address") or ""
    if isinstance(value, (list, tuple)):
        for item in value:
            found.extend(_addresses_from_value(item))
        return found
    for match in _ADDRESS_RE.findall(str(value)):
        found.append(match.lower())
    return found


def recipient_addresses(data: Mapping) -> list[str]:
    """All recipient addresses in an email.received payload. `received_for` is
    Resend's envelope recipient — the address the mail was actually delivered
    to, which catches forwards/aliases where To/Cc don't show our reply+."""
    seen: list[str] = []
    for field in ("to", "cc", "bcc", "received_for"):
        for addr in _addresses_from_value(data.get(field)):
            if addr not in seen:
                seen.append(addr)
    return seen


def sender_address(data: Mapping) -> Optional[str]:
    addrs = _addresses_from_value(data.get("from"))
    return addrs[0] if addrs else None


def html_to_text(html: str) -> str:
    """Very small HTML→text fallback for html-only replies."""
    if not html:
        return ""
    text = re.sub(r"(?is)<(style|script|head)[^>]*>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li|blockquote|h[1-6])>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n\s*\n+", "\n\n", text)
    return text.strip()


_QUOTE_LINE_MARKERS = (
    re.compile(r"^On .{0,300}wrote:\s*$", re.IGNORECASE),
    re.compile(r"^-{2,}\s*Original Message\s*-{2,}\s*$", re.IGNORECASE),
    re.compile(r"^_{4,}\s*$"),
    re.compile(r"^-{2,}\s*Forwarded message\s*-{2,}\s*$", re.IGNORECASE),
)


def strip_quoted_reply(text: str) -> str:
    """Cut the quoted history off a reply (conservative: on any doubt, keep).
    Falls back to the full text if stripping would leave nothing."""
    if not text:
        return ""
    lines = text.replace("\r\n", "\n").split("\n")
    cut = len(lines)
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(">"):
            cut = i
            break
        if any(marker.match(stripped) for marker in _QUOTE_LINE_MARKERS):
            cut = i
            break
        # Outlook-style header block: "From: ..." followed shortly by Sent:/Date:/To:
        if re.match(r"^From:\s*\S", stripped, re.IGNORECASE):
            lookahead = [l.strip() for l in lines[i + 1:i + 4]]
            if any(re.match(r"^(Sent|Date|To|Subject):\s*\S", l, re.IGNORECASE) for l in lookahead):
                cut = i
                break
    result = "\n".join(lines[:cut]).strip()
    return result if result else text.strip()


def fetch_inbound_body(email_id: str) -> tuple[Optional[str], Optional[str], bool]:
    """Fetch (text, html, ok) for an inbound email — the email.received webhook
    carries metadata only, so the body always comes from the API. ok=True means
    we got an authoritative response (even if the email genuinely has no body);
    ok=False means every fetch path errored, so the caller should let the
    provider RETRY rather than store an empty reply. Tries the SDK's receiving
    API first, then a raw REST call (older SDKs lack EmailsReceiving)."""
    if not email_id:
        return None, None, False

    def _bodies(fetched) -> tuple[Optional[str], Optional[str]]:
        if isinstance(fetched, Mapping):
            return fetched.get("text"), fetched.get("html")
        return getattr(fetched, "text", None), getattr(fetched, "html", None)

    try:
        import resend
    except Exception:
        resend = None
    if resend is not None:
        cls = getattr(resend, "EmailsReceiving", None)
        getter = getattr(cls, "get", None) if cls is not None else None
        if getter is not None:
            try:
                fetched = getter(email_id)
            except Exception:
                logger.info("inbound-email: EmailsReceiving.get(%s) failed", email_id, exc_info=True)
            else:
                if fetched is not None:
                    text_body, html_body = _bodies(fetched)
                    return text_body, html_body, True

    # Raw REST fallback (same endpoint the SDK uses), with a bounded timeout.
    api_key = (os.getenv("RESEND_API_KEY") or "").strip()
    if api_key:
        try:
            import requests
            resp = requests.get(
                f"https://api.resend.com/emails/receiving/{email_id}",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=10,
            )
            if resp.status_code == 200:
                payload = resp.json()
                if isinstance(payload, dict):
                    return payload.get("text"), payload.get("html"), True
        except Exception:
            logger.info("inbound-email: raw receiving fetch for %s failed", email_id, exc_info=True)
    return None, None, False


def extract_reply_text(data: Mapping) -> tuple[str, bool]:
    """(reply_text, fetch_failed) for an inbound email: payload text, payload
    html, or an API fetch by email id — quoted history stripped. fetch_failed
    is True when the body had to be fetched and every fetch path errored; the
    webhook should then 5xx so the provider retries instead of losing the body."""
    text_body = data.get("text")
    html_body = data.get("html")
    fetch_failed = False
    if not text_body and not html_body:
        email_id = str(data.get("email_id") or data.get("id") or "").strip()
        if email_id:
            text_body, html_body, ok = fetch_inbound_body(email_id)
            fetch_failed = not ok
    if not text_body and html_body:
        text_body = html_to_text(str(html_body))
    return strip_quoted_reply(str(text_body or "").strip()), fetch_failed
