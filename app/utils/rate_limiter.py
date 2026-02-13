import os
import random
import threading
import time
from collections import defaultdict, deque
from typing import Optional, Tuple

from fastapi import Request
from sqlalchemy import text

from app.database import engine


def _is_truthy(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _parse_csv_set(raw: str) -> set[str]:
    return {item.strip() for item in (raw or "").split(",") if item.strip()}


TRUST_PROXY_HEADERS = _is_truthy(os.getenv("TRUST_PROXY_HEADERS", "false"))
TRUSTED_PROXY_IPS = _parse_csv_set(os.getenv("TRUSTED_PROXY_IPS", ""))
RATE_LIMIT_BACKEND = (os.getenv("RATE_LIMIT_BACKEND", "database").strip().lower() or "database")


class InMemoryRateLimiter:
    """
    Simple fixed-window in-memory rate limiter.
    Suitable for local/single-instance deployments.
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


class DatabaseRateLimiter:
    """
    DB-backed fixed-window rate limiter.
    Works across multiple app instances sharing the same DB.
    """

    def __init__(self) -> None:
        self._initialized = False
        self._lock = threading.Lock()

    def _ensure_table(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            with engine.begin() as conn:
                if engine.dialect.name == "sqlite":
                    conn.execute(
                        text(
                            """
                            CREATE TABLE IF NOT EXISTS rate_limit_buckets (
                                rate_key TEXT NOT NULL,
                                window_start INTEGER NOT NULL,
                                request_count INTEGER NOT NULL DEFAULT 0,
                                updated_at INTEGER NOT NULL,
                                PRIMARY KEY (rate_key, window_start)
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(
                            """
                            CREATE INDEX IF NOT EXISTS idx_rate_limit_buckets_updated_at
                            ON rate_limit_buckets (updated_at)
                            """
                        )
                    )
                else:
                    conn.execute(
                        text(
                            """
                            CREATE TABLE IF NOT EXISTS rate_limit_buckets (
                                rate_key VARCHAR(255) NOT NULL,
                                window_start BIGINT NOT NULL,
                                request_count INTEGER NOT NULL DEFAULT 0,
                                updated_at BIGINT NOT NULL,
                                PRIMARY KEY (rate_key, window_start)
                            )
                            """
                        )
                    )
                    conn.execute(
                        text(
                            """
                            CREATE INDEX IF NOT EXISTS idx_rate_limit_buckets_updated_at
                            ON rate_limit_buckets (updated_at)
                            """
                        )
                    )
            self._initialized = True

    def allow(self, key: str, limit: int, window_seconds: int) -> Tuple[bool, int]:
        self._ensure_table()
        now = int(time.time())
        window_start = now - (now % max(window_seconds, 1))

        # Best-effort cleanup (1% of requests) to prevent table growth.
        do_cleanup = random.randint(1, 100) == 1
        cleanup_before = window_start - (window_seconds * 4)

        with engine.begin() as conn:
            if do_cleanup:
                conn.execute(
                    text("DELETE FROM rate_limit_buckets WHERE updated_at < :cleanup_before"),
                    {"cleanup_before": cleanup_before},
                )

            conn.execute(
                text(
                    """
                    INSERT INTO rate_limit_buckets (rate_key, window_start, request_count, updated_at)
                    VALUES (:rate_key, :window_start, 1, :updated_at)
                    ON CONFLICT (rate_key, window_start)
                    DO UPDATE SET
                        request_count = rate_limit_buckets.request_count + 1,
                        updated_at = :updated_at
                    """
                ),
                {
                    "rate_key": key,
                    "window_start": window_start,
                    "updated_at": now,
                },
            )

            row = conn.execute(
                text(
                    """
                    SELECT request_count
                    FROM rate_limit_buckets
                    WHERE rate_key = :rate_key AND window_start = :window_start
                    """
                ),
                {"rate_key": key, "window_start": window_start},
            ).first()
            request_count = int(row[0] if row else 0)

        if request_count > limit:
            retry_after = int(max(1, (window_start + window_seconds) - now))
            return False, retry_after

        return True, 0


in_memory_rate_limiter = InMemoryRateLimiter()
database_rate_limiter = DatabaseRateLimiter()


def _should_trust_proxy_headers(request: Request) -> bool:
    if not TRUST_PROXY_HEADERS:
        return False
    if not TRUSTED_PROXY_IPS:
        # If proxy trust is enabled but trusted IPs are not pinned, keep header trust disabled.
        return False
    remote_host = request.client.host if request.client and request.client.host else ""
    return remote_host in TRUSTED_PROXY_IPS


def extract_client_ip(request: Request) -> str:
    """
    Resolve client IP with optional strict proxy-header support.
    """
    if _should_trust_proxy_headers(request):
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

    use_database_backend = RATE_LIMIT_BACKEND == "database" and engine.dialect.name in {"postgresql", "sqlite"}
    if use_database_backend:
        try:
            return database_rate_limiter.allow(key=key, limit=limit, window_seconds=window_seconds)
        except Exception:
            # Fail open to in-memory limiter to avoid blocking auth/payment flows on transient DB issues.
            return in_memory_rate_limiter.allow(key=key, limit=limit, window_seconds=window_seconds)

    return in_memory_rate_limiter.allow(key=key, limit=limit, window_seconds=window_seconds)
