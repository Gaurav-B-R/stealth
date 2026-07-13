"""
UK Student-visa maintenance figures — one server-side source of truth.

The public tool page, the B2C Stage-4 modal and the Enterprise CRM all fetch these from
/api/tools/uk-maintenance-figures instead of hardcoding them in JS, so the amounts can be
updated without shipping new frontend code.

The living-cost rates are the Home Office "money" requirement, which changes periodically
(they rose in Jan 2025). We keep a human-verified baseline (env-overridable, so a rate change
can be applied with an env var and no code deploy) and, when enabled, best-effort scrape the
live GOV.UK figures — accepting them ONLY inside strict sanity bounds, otherwise serving the
baseline. Every surface still hedges with a "confirm on GOV.UK" note. Modeled on app/fx.py.

Env: UK_MAINT_LIVE_ENABLED, UK_MAINT_SOURCE_URL, UK_MAINT_TTL_SECONDS, UK_MAINT_RETRY_SECONDS,
UK_MAINT_TIMEOUT_SECONDS, and baseline overrides UK_MAINT_LONDON, UK_MAINT_OUTSIDE,
UK_MAINT_ACCOM_CAP, UK_MAINT_MAX_MONTHS, UK_MAINT_AS_OF.
"""
from __future__ import annotations

import os
import re
import time
import threading
import logging

import requests

logger = logging.getLogger(__name__)


def _num_env(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, "") or default)
    except Exception:
        return float(default)


# Human-verified baseline — confirmed against GOV.UK on 2026-07-12 (rates rose from the
# Jan-2025 £1,483/£1,136). Override any value via env, no code deploy. This is only the
# fallback; the live GOV.UK check below keeps it current automatically when reachable.
BASELINE = {
    "london": _num_env("UK_MAINT_LONDON", 1529),       # £/month living costs, studying in London
    "outside": _num_env("UK_MAINT_OUTSIDE", 1171),      # £/month living costs, outside London
    "accomCap": _num_env("UK_MAINT_ACCOM_CAP", 1334),   # max accommodation prepayment you can offset
    "maxMonths": int(_num_env("UK_MAINT_MAX_MONTHS", 9)),  # living costs capped at 9 months
    "asOf": (os.getenv("UK_MAINT_AS_OF", "").strip() or "July 2026"),
}
SOURCE_URL = (os.getenv("UK_MAINT_SOURCE_URL", "").strip() or "https://www.gov.uk/student-visa/money")
PUBLIC_PATH = "/tools/uk-maintenance-calculator"
_BASELINE_IS_ENV = bool(os.getenv("UK_MAINT_LONDON") or os.getenv("UK_MAINT_OUTSIDE"))

LIVE_ENABLED = str(os.getenv("UK_MAINT_LIVE_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}
TIMEOUT = _num_env("UK_MAINT_TIMEOUT_SECONDS", 5)
TTL = int(_num_env("UK_MAINT_TTL_SECONDS", 86400))       # figures change ~yearly; re-check daily
RETRY = int(_num_env("UK_MAINT_RETRY_SECONDS", 3600))    # after a failure, wait 1h before retrying

# Sanity bounds so a bad scrape can never feed a student a wrong number. London must exceed
# outside-London, and both must sit inside a plausible band around the historical figures.
_LON_MIN, _LON_MAX = 1200.0, 2500.0
_OUT_MIN, _OUT_MAX = 900.0, 2000.0

_lock = threading.Lock()
_state: dict = {
    "london": None, "outside": None, "source": "fallback",
    "fetched_at": 0.0, "last_attempt": 0.0,
}


def _fetch_live():
    """Best-effort scrape of the two monthly living-cost figures from GOV.UK.
    Returns (london, outside) only when both parse inside the sanity bounds, else None."""
    try:
        resp = requests.get(
            SOURCE_URL, timeout=TIMEOUT,
            headers={"User-Agent": "RilonoBot/1.0 (+https://rilono.com)"},
        )
        resp.raise_for_status()
        # Flatten markup to plain text so wording/markup variations don't matter.
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", resp.text or ""))
        london = outside = None
        # Each rate reads like "£1,136 per month (for up to 9 months) if you're studying
        # outside London". [^£] stops the context window before the next amount so the
        # London bullet can't accidentally absorb the "outside London" that follows it.
        for m in re.finditer(r"£\s*([\d,]+)\s*(?:per month|a month)([^£]{0,180})", text, re.I):
            try:
                amt = float(m.group(1).replace(",", ""))
            except Exception:
                continue
            ctx = (m.group(2) or "").lower()
            if "outside london" in ctx or "outside of london" in ctx:
                outside = outside or amt
            elif "london" in ctx:
                london = london or amt
        if (london and outside and london > outside
                and _LON_MIN <= london <= _LON_MAX and _OUT_MIN <= outside <= _OUT_MAX):
            return london, outside
        logger.warning("UK maintenance scrape rejected (london=%s outside=%s)", london, outside)
    except Exception:
        logger.warning("UK maintenance live fetch failed from %s", SOURCE_URL, exc_info=True)
    return None


def _resolve(force: bool = False):
    """Return (london, outside, source, fetched_at), fetching live when the cache is stale."""
    now = time.time()
    with _lock:
        have = _state["london"] is not None
        fresh = have and (now - _state["fetched_at"]) < TTL
        recently_tried = (now - _state["last_attempt"]) < RETRY
        # Serve cache if fresh, or if we just tried (don't hammer a slow/blocked GOV.UK).
        if (fresh or (have and recently_tried)) and not force:
            return _state["london"], _state["outside"], _state["source"], _state["fetched_at"]
        _state["last_attempt"] = now

    live = _fetch_live() if LIVE_ENABLED else None

    with _lock:
        if live is not None:
            _state.update(london=live[0], outside=live[1], source="live", fetched_at=time.time())
        elif _state["london"] is None:
            _state.update(
                london=BASELINE["london"], outside=BASELINE["outside"],
                source=("env" if _BASELINE_IS_ENV else "fallback"), fetched_at=time.time(),
            )
        # else: keep the last-known live values (better than dropping to the baseline).
        return _state["london"], _state["outside"], _state["source"], _state["fetched_at"]


def get_figures(force: bool = False) -> dict:
    """The full figure set the frontend needs, with live living-cost rates when available."""
    london, outside, source, fetched_at = _resolve(force)
    return {
        "london": london,
        "outside": outside,
        "accomCap": BASELINE["accomCap"],
        "maxMonths": BASELINE["maxMonths"],
        # asOf is meaningful for our verified baseline; for a live-scraped rate we don't know
        # the effective date, so the UI shows a "live from GOV.UK" badge instead.
        "asOf": BASELINE["asOf"],
        "source": source,          # "live" | "fallback" | "env"
        "sourceUrl": SOURCE_URL,
        "publicPath": PUBLIC_PATH,
        "checkedAt": fetched_at,
    }


def prime() -> None:
    """Warm the cache in a background thread at startup so the first page load doesn't pay
    the GOV.UK round-trip."""
    try:
        threading.Thread(target=_resolve, name="uk-maint-prime", daemon=True).start()
    except Exception:
        logger.debug("UK maintenance prime thread failed to start", exc_info=True)
