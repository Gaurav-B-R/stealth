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

Provenance is reported PER FIELD (`fieldSources`), not just once for the payload. The scrape
can succeed for the monthly rates and fail for the accommodation-offset cap, and a figure a
student holds in a bank account must never be badged "live from GOV.UK" when it actually came
from the hardcoded baseline. The top-level `source` is therefore "live" only when every
monetary figure in the payload was live-verified, and "mixed" when only some were.

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


# Human-verified baseline — confirmed against GOV.UK on 2026-08-07 (rates rose from the
# Jan-2025 £1,483/£1,136). The accommodation-prepayment offset cap is £1,529, in force since
# 11 November 2025 under Immigration Rules Appendix Student ST 12.4 — see RULES_URL below.
# Override any value via env, no code deploy. This is only the fallback; the live GOV.UK
# check below keeps the monthly rates current automatically when reachable.
BASELINE = {
    "london": _num_env("UK_MAINT_LONDON", 1529),       # £/month living costs, studying in London
    "outside": _num_env("UK_MAINT_OUTSIDE", 1171),      # £/month living costs, outside London
    "accomCap": _num_env("UK_MAINT_ACCOM_CAP", 1529),   # max accommodation prepayment you can offset
    "maxMonths": int(_num_env("UK_MAINT_MAX_MONTHS", 9)),  # living costs capped at 9 months
    "asOf": (os.getenv("UK_MAINT_AS_OF", "").strip() or "August 2026"),
}
SOURCE_URL = (os.getenv("UK_MAINT_SOURCE_URL", "").strip() or "https://www.gov.uk/student-visa/money")
# The underlying rule for the offset cap (ST 12.4), quoted by the public pages.
RULES_URL = "https://www.gov.uk/guidance/immigration-rules/immigration-rules-appendix-student"
PUBLIC_PATH = "/tools/uk-maintenance-calculator"
_BASELINE_IS_ENV = bool(os.getenv("UK_MAINT_LONDON") or os.getenv("UK_MAINT_OUTSIDE"))
# Provenance of the baseline cap when the live read doesn't produce one.
_CAP_BASELINE_SOURCE = "env" if os.getenv("UK_MAINT_ACCOM_CAP") else "fallback"
_MONTHS_SOURCE = "env" if os.getenv("UK_MAINT_MAX_MONTHS") else "fallback"

LIVE_ENABLED = str(os.getenv("UK_MAINT_LIVE_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}
TIMEOUT = _num_env("UK_MAINT_TIMEOUT_SECONDS", 5)
TTL = int(_num_env("UK_MAINT_TTL_SECONDS", 86400))       # figures change ~yearly; re-check daily
RETRY = int(_num_env("UK_MAINT_RETRY_SECONDS", 3600))    # after a failure, wait 1h before retrying

# Sanity bounds so a bad scrape can never feed a student a wrong number. London must exceed
# outside-London, and both must sit inside a plausible band around the historical figures.
_LON_MIN, _LON_MAX = 1200.0, 2500.0
_OUT_MIN, _OUT_MAX = 900.0, 2000.0
_CAP_MIN, _CAP_MAX = 1000.0, 2500.0

_lock = threading.Lock()
_state: dict = {
    "london": None, "outside": None, "accomCap": None,
    "source": "fallback", "capSource": _CAP_BASELINE_SOURCE,
    "fetched_at": 0.0, "last_attempt": 0.0,
}


def _parse_accom_cap(text: str):
    """Opportunistically parse the accommodation-prepayment offset cap from the scraped page.

    As checked on 2026-08-07, SOURCE_URL (the GOV.UK "money you need" page) does not mention
    accommodation at all — the cap lives in Immigration Rules Appendix Student ST 12.4
    (RULES_URL), which is not machine-friendly. So in practice this returns None and the
    human-verified BASELINE is served, reported as "fallback" rather than "live". This stays
    here so that if GOV.UK does publish the sentence ("...you can use up to £X of it"), we pick
    it up: we accept an amount only when it sits in a sentence mentioning accommodation, is
    introduced by "up to", is not one of the per-month living-cost rates, and lands inside the
    sanity bounds. Returns the amount or None."""
    for m in re.finditer(r"([^.£]{0,220})£\s*([\d,]+)([^.£]{0,220})", text):
        before, after = (m.group(1) or "").lower(), (m.group(3) or "").lower()
        if "accommodation" not in (before + " " + after):
            continue
        if "up to" not in before[-40:]:
            continue
        if after[:24].strip().startswith(("per month", "a month")):
            continue
        try:
            amt = float(m.group(2).replace(",", ""))
        except Exception:
            continue
        if _CAP_MIN <= amt <= _CAP_MAX:
            return amt
    return None


def _fetch_live():
    """Best-effort scrape of the monthly living-cost figures (and, when the page states it,
    the accommodation-offset cap) from GOV.UK.
    Returns (london, outside, accom_cap_or_None) only when the two rates parse inside the
    sanity bounds, else None."""
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
            cap = _parse_accom_cap(text)
            if cap is None:
                # Expected today — logged so the baseline cap can't sit unreviewed for a year
                # again. Re-verify it by hand against RULES_URL when this shows up in the logs.
                logger.info("UK maintenance: offset cap not stated at %s; serving baseline "
                            "£%s (verify against %s)", SOURCE_URL, BASELINE["accomCap"], RULES_URL)
            return london, outside, cap
        logger.warning("UK maintenance scrape rejected (london=%s outside=%s)", london, outside)
    except Exception:
        logger.warning("UK maintenance live fetch failed from %s", SOURCE_URL, exc_info=True)
    return None


def _snapshot() -> tuple:
    return (_state["london"], _state["outside"], _state["accomCap"],
            _state["source"], _state["capSource"], _state["fetched_at"])


def _resolve(force: bool = False):
    """Return (london, outside, accomCap, source, capSource, fetched_at), fetching live when
    the cache is stale. `source` covers the monthly rates, `capSource` the offset cap — they
    diverge whenever the page states the rates but not the cap."""
    now = time.time()
    with _lock:
        have = _state["london"] is not None
        fresh = have and (now - _state["fetched_at"]) < TTL
        recently_tried = (now - _state["last_attempt"]) < RETRY
        # Serve cache if fresh, or if we just tried (don't hammer a slow/blocked GOV.UK).
        if (fresh or (have and recently_tried)) and not force:
            return _snapshot()
        _state["last_attempt"] = now

    live = _fetch_live() if LIVE_ENABLED else None

    with _lock:
        if live is not None:
            london, outside, cap = live
            _state.update(london=london, outside=outside, source="live", fetched_at=time.time())
            # The cap is only "live" when we actually read it off the page this time.
            if cap is not None:
                _state.update(accomCap=cap, capSource="live")
            else:
                _state.update(accomCap=BASELINE["accomCap"], capSource=_CAP_BASELINE_SOURCE)
        elif _state["london"] is None:
            _state.update(
                london=BASELINE["london"], outside=BASELINE["outside"],
                accomCap=BASELINE["accomCap"],
                source=("env" if _BASELINE_IS_ENV else "fallback"),
                capSource=_CAP_BASELINE_SOURCE, fetched_at=time.time(),
            )
        # else: keep the last-known live values (better than dropping to the baseline).
        return _snapshot()


def get_figures(force: bool = False) -> dict:
    """The full figure set the frontend needs, with live living-cost rates when available.

    Every figure carries its own provenance in `fieldSources` so no surface can badge a
    hardcoded constant as live-verified."""
    london, outside, accom_cap, source, cap_source, fetched_at = _resolve(force)
    field_sources = {
        "london": source,
        "outside": source,
        "accomCap": cap_source,
        # A rule constant, not a scraped amount — always ours, never live-verified.
        "maxMonths": _MONTHS_SOURCE,
    }
    # The headline badge may only say "live" when every monetary figure below really was
    # read from GOV.UK on this check; otherwise it degrades to "mixed" and the UI names
    # which figures are live. maxMonths is excluded — it is a rule, not an amount.
    monetary = (field_sources["london"], field_sources["outside"], field_sources["accomCap"])
    overall = source if all(s == source for s in monetary) else "mixed"
    return {
        "london": london,
        "outside": outside,
        "accomCap": accom_cap,
        "maxMonths": BASELINE["maxMonths"],
        # asOf is meaningful for our verified baseline; for a live-scraped rate we don't know
        # the effective date, so the UI shows a "live from GOV.UK" badge instead.
        "asOf": BASELINE["asOf"],
        "source": overall,          # "live" | "mixed" | "fallback" | "env"
        "fieldSources": field_sources,
        "sourceUrl": SOURCE_URL,
        "rulesUrl": RULES_URL,
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
