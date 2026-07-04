"""
Dynamic USD → INR exchange rate.

Gemini API costs are tracked in USD; the admin margin reports convert them to INR.
This fetches a LIVE rate from a keyless FX API, caches it in-memory (FX doesn't move
much and the reports are estimates), and falls back to the static USD_TO_INR env value
if the live fetch fails — so the reports always render, just with a stale/estimated rate.

All tunable via env: FX_LIVE_ENABLED, FX_API_URL, FX_CACHE_TTL_SECONDS, FX_RETRY_SECONDS,
FX_TIMEOUT_SECONDS, USD_TO_INR (fallback).
"""
from __future__ import annotations

import os
import time
import threading
import logging

import requests

logger = logging.getLogger(__name__)

# Static fallback (the historical value); the live rate overrides it when available.
FALLBACK_USD_TO_INR = float(os.getenv("USD_TO_INR", "86") or "86")
LIVE_ENABLED = str(os.getenv("FX_LIVE_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}
# open.er-api.com is keyless and returns { "rates": { "INR": <rate>, ... } }.
API_URL = (os.getenv("FX_API_URL", "https://open.er-api.com/v6/latest/USD").strip()
           or "https://open.er-api.com/v6/latest/USD")
TIMEOUT = float(os.getenv("FX_TIMEOUT_SECONDS", "4") or "4")
TTL = int(os.getenv("FX_CACHE_TTL_SECONDS", "43200") or "43200")   # refresh at most every 12h
RETRY = int(os.getenv("FX_RETRY_SECONDS", "600") or "600")         # after a failure, wait before retrying

# Sanity bounds so a bad API value can't wreck the margin reports.
_MIN, _MAX = 40.0, 200.0

_lock = threading.Lock()
_state: dict = {"rate": None, "source": "fallback", "fetched_at": 0.0, "last_attempt": 0.0}


def _fetch_live() -> float | None:
    try:
        resp = requests.get(API_URL, timeout=TIMEOUT)
        resp.raise_for_status()
        data = resp.json() or {}
        raw = (data.get("rates") or {}).get("INR")
        rate = float(raw) if raw is not None else None
        if rate and _MIN <= rate <= _MAX:
            return rate
        logger.warning("FX rate missing/out-of-bounds from %s: %s", API_URL, raw)
    except Exception:
        logger.warning("FX live fetch failed from %s", API_URL, exc_info=True)
    return None


def get_state(force: bool = False) -> dict:
    """Return {rate, source, fetched_at, last_attempt}. Fetches live when stale."""
    now = time.time()
    with _lock:
        have = _state["rate"] is not None
        fresh = have and (now - _state["fetched_at"]) < TTL
        recently_tried = (now - _state["last_attempt"]) < RETRY
        # Serve cache if the rate is fresh, or we just tried (don't hammer a down API).
        if (fresh or (have and recently_tried)) and not force:
            return dict(_state)
        _state["last_attempt"] = now

    rate = _fetch_live() if LIVE_ENABLED else None

    with _lock:
        if rate is not None:
            _state.update(rate=rate, source="live", fetched_at=time.time())
        elif _state["rate"] is None:
            _state.update(rate=FALLBACK_USD_TO_INR, source="fallback", fetched_at=time.time())
        # else: keep the last-known live rate (better than dropping to the static fallback)
        return dict(_state)


def get_usd_to_inr(force: bool = False) -> float:
    return float(get_state(force)["rate"] or FALLBACK_USD_TO_INR)


def prime() -> None:
    """Warm the cache in a background thread (call once at startup) so the first
    admin report doesn't pay the network round-trip."""
    try:
        threading.Thread(target=get_state, name="fx-prime", daemon=True).start()
    except Exception:
        logger.debug("FX prime thread failed to start", exc_info=True)
