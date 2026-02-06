from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any, Dict

import requests
from fastapi import APIRouter, Query

router = APIRouter(prefix="/api/pricing", tags=["pricing"])

SUPPORTED_CURRENCIES = ("USD", "INR", "GBP", "CAD", "AUD", "EUR", "AED", "SGD", "JPY")
FRANKFURTER_SUPPORTED_CURRENCIES = ("USD", "INR", "GBP", "CAD", "AUD", "EUR", "SGD", "JPY")
FALLBACK_RATES = {
    "USD": 1.0,
    "INR": 83.2,
    "GBP": 0.79,
    "CAD": 1.35,
    "AUD": 1.53,
    "EUR": 0.92,
    "AED": 3.67,
    "SGD": 1.35,
    "JPY": 149.0,
}
RATES_CACHE_TTL = timedelta(hours=24)
FRANKFURTER_URL = "https://api.frankfurter.app/latest"

_rates_cache: Dict[str, Any] = {
    "rates": None,
    "provider_date": None,
    "fetched_at": None,
    "source": "fallback",
    "missing_currencies": [],
}
_rates_lock = Lock()


def _build_payload(
    rates: Dict[str, float],
    source: str,
    missing_currencies: list = None,
    provider_date: str = None,
    fetched_at: datetime = None,
    cached: bool = False,
    stale: bool = False,
) -> Dict[str, Any]:
    return {
        "base": "USD",
        "rates": rates,
        "source": source,
        "missing_currencies": missing_currencies or [],
        "provider_date": provider_date,
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
        "cached": cached,
        "stale": stale,
    }


def _cache_is_fresh(now_utc: datetime) -> bool:
    if not _rates_cache["rates"] or not _rates_cache["fetched_at"]:
        return False
    return (now_utc - _rates_cache["fetched_at"]) < RATES_CACHE_TTL


def _fetch_rates_from_frankfurter() -> Dict[str, Any]:
    symbols = ",".join(currency for currency in FRANKFURTER_SUPPORTED_CURRENCIES if currency != "USD")
    response = requests.get(
        FRANKFURTER_URL,
        params={"from": "USD", "to": symbols},
        timeout=10,
    )
    response.raise_for_status()

    data = response.json()
    provider_rates = data.get("rates", {})

    rates: Dict[str, float] = dict(FALLBACK_RATES)
    missing_currencies = []
    rates["USD"] = 1.0

    for currency in FRANKFURTER_SUPPORTED_CURRENCIES:
        if currency == "USD":
            continue
        raw_rate = provider_rates.get(currency)
        if isinstance(raw_rate, (int, float)) and raw_rate > 0:
            rates[currency] = float(raw_rate)
        else:
            missing_currencies.append(currency)

    for currency in SUPPORTED_CURRENCIES:
        if currency not in FRANKFURTER_SUPPORTED_CURRENCIES:
            missing_currencies.append(currency)

    provider_date = data.get("date")
    source = "frankfurter_partial" if missing_currencies else "frankfurter"
    return {
        "rates": rates,
        "provider_date": provider_date,
        "source": source,
        "missing_currencies": missing_currencies,
    }


@router.get("/exchange-rates")
def get_exchange_rates(refresh: bool = Query(default=False)) -> Dict[str, Any]:
    now_utc = datetime.now(timezone.utc)

    with _rates_lock:
        if not refresh and _cache_is_fresh(now_utc):
            return _build_payload(
                rates=_rates_cache["rates"],
                source=_rates_cache["source"],
                missing_currencies=_rates_cache["missing_currencies"],
                provider_date=_rates_cache["provider_date"],
                fetched_at=_rates_cache["fetched_at"],
                cached=True,
                stale=False,
            )

        try:
            latest = _fetch_rates_from_frankfurter()
            _rates_cache["rates"] = latest["rates"]
            _rates_cache["provider_date"] = latest["provider_date"]
            _rates_cache["fetched_at"] = now_utc
            _rates_cache["source"] = latest["source"]
            _rates_cache["missing_currencies"] = latest["missing_currencies"]
            return _build_payload(
                rates=latest["rates"],
                source=latest["source"],
                missing_currencies=latest["missing_currencies"],
                provider_date=latest["provider_date"],
                fetched_at=now_utc,
                cached=False,
                stale=False,
            )
        except Exception:
            if _rates_cache["rates"]:
                return _build_payload(
                    rates=_rates_cache["rates"],
                    source=_rates_cache["source"],
                    missing_currencies=_rates_cache["missing_currencies"],
                    provider_date=_rates_cache["provider_date"],
                    fetched_at=_rates_cache["fetched_at"],
                    cached=True,
                    stale=True,
                )

            return _build_payload(
                rates=FALLBACK_RATES,
                source="fallback",
                provider_date=None,
                fetched_at=now_utc,
                cached=False,
                stale=True,
            )
