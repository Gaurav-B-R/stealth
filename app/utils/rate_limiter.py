import os
import threading
import time
from collections import defaultdict, deque
from typing import Optional, Tuple

from fastapi import Request


def _is_truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


TRUST_PROXY_HEADERS = _is_truthy(os.getenv("TRUST_PROXY_HEADERS", "true"))


class InMemoryRateLimiter:
    """
    Simple fixed-window in-memory rate limiter.
    Suitable for single-instance deployments.
    """

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int]:
        now = time.time()
        cutoff = now - window_seconds

        with self._lock:
            events = self._events[key]
            while events and events[0] <= cutoff:
                events.popleft()

            if len(events) >= limit:
                retry_after = int(max(1, window_seconds - (now - events[0])))
                return False, retry_after

            events.append(now)
            return True, 0


rate_limiter = InMemoryRateLimiter()


def extract_client_ip(request: Request) -> str:
    """
    Resolve client IP with optional proxy-header support.
    """
    if TRUST_PROXY_HEADERS:
        cf_ip = request.headers.get("cf-connecting-ip")
        if cf_ip:
            return cf_ip.strip()

        xff = request.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[0].strip()

        xrip = request.headers.get("x-real-ip")
        if xrip:
            return xrip.strip()

    if request.client and request.client.host:
        return request.client.host

    return "unknown"


def check_ip_rate_limit(
    request: Request,
    scope: str,
    limit: int,
    window_seconds: int,
    extra_key: Optional[str] = None,
) -> Tuple[bool, int]:
    ip = extract_client_ip(request)
    key = f"{scope}:{ip}"
    if extra_key:
        key = f"{key}:{extra_key}"
    return rate_limiter.allow(key, limit, window_seconds)
