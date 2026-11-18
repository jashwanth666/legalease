"""Pluggable sliding-window rate limiter with true Redis (distributed) and in-memory (dev) backends.

Usage
-----
Call ``get_rate_limiter(settings)`` to obtain the shared limiter instance.
Call ``limiter.check(action, client_ip, max_attempts, window_seconds)`` on every
sensitive request; it raises ``RateLimitExceeded`` when the caller is over the limit.

In production mode (``ENVIRONMENT=production``), if Redis is configured or required,
connection failures raise an exception immediately rather than silently failing open.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from backend.config import Settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class RateLimitExceeded(Exception):
    """Raised when the caller has exceeded the allowed request rate."""


# ---------------------------------------------------------------------------
# Abstract base
# ---------------------------------------------------------------------------


class RateLimiter(ABC):
    """Pluggable sliding-window rate limiter interface."""

    def __init__(self, max_attempts: int = 60, window_seconds: float = 60.0) -> None:
        self.default_max_attempts = max_attempts
        self.default_window_seconds = window_seconds

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """Return the active backend type string ('redis' or 'inmemory')."""

    @abstractmethod
    def check(
        self,
        action: str,
        client_ip: str,
        max_attempts: int | None = None,
        window_seconds: float | None = None,
    ) -> None:
        """Record an attempt and raise ``RateLimitExceeded`` if limit is exceeded."""

    @abstractmethod
    def reset(self, action: str | None = None, client_ip: str | None = None) -> None:
        """Clear rate-limit windows (used in tests and administrative maintenance)."""


# ---------------------------------------------------------------------------
# In-memory backend (dev / single-process)
# ---------------------------------------------------------------------------


@dataclass
class InMemoryRateLimiter(RateLimiter):
    """Thread-safe sliding-window in-memory rate limiter.

    Tracks each ``"{action}:{ip}"`` key independently using timestamps.
    Timestamps outside the rolling window are pruned automatically.
    """

    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _windows: dict[str, list[float]] = field(default_factory=dict, init=False, repr=False)

    def __init__(self, max_attempts: int = 60, window_seconds: float = 60.0) -> None:
        super().__init__(max_attempts=max_attempts, window_seconds=window_seconds)
        self._lock = threading.Lock()
        self._windows: dict[str, list[float]] = {}

    @property
    def backend_type(self) -> str:
        return "inmemory"

    def _key(self, action: str, client_ip: str) -> str:
        return f"{action}:{client_ip}"

    def check(
        self,
        action: str,
        client_ip: str,
        max_attempts: int | None = None,
        window_seconds: float | None = None,
    ) -> None:
        limit = max_attempts if max_attempts is not None else self.default_max_attempts
        window = window_seconds if window_seconds is not None else self.default_window_seconds
        key = self._key(action, client_ip)
        now = time.monotonic()
        cutoff = now - window
        with self._lock:
            timestamps = [t for t in self._windows.get(key, []) if t >= cutoff]
            if len(timestamps) >= limit:
                self._windows[key] = timestamps
                raise RateLimitExceeded(
                    f"Too many '{action}' attempts from {client_ip}. "
                    f"Please wait {int(window)} seconds before retrying."
                )
            timestamps.append(now)
            self._windows[key] = timestamps

    def reset(self, action: str | None = None, client_ip: str | None = None) -> None:
        with self._lock:
            if action is None and client_ip is None:
                self._windows.clear()
            elif action is not None and client_ip is not None:
                self._windows.pop(self._key(action, client_ip), None)
            elif action is not None:
                prefix = f"{action}:"
                for k in list(self._windows.keys()):
                    if k.startswith(prefix):
                        del self._windows[k]
            else:
                suffix = f":{client_ip}"
                for k in list(self._windows.keys()):
                    if k.endswith(suffix):
                        del self._windows[k]


# ---------------------------------------------------------------------------
# True Redis Sliding-Window Backend (production / distributed)
# ---------------------------------------------------------------------------

# Atomic Redis Lua script implementing a true sliding window using Sorted Sets (ZSET).
# ARGV[1] = current timestamp (float)
# ARGV[2] = window length in seconds (float)
# ARGV[3] = max allowed attempts (integer)
# ARGV[4] = unique member identifier
_SLIDING_WINDOW_LUA = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local clear_before = now - window

redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)
local current_requests = redis.call('ZCARD', key)
if current_requests >= limit then
    return 0
else
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, math.ceil(window) + 1)
    return 1
end
"""


class RedisRateLimiter(RateLimiter):
    """Distributed true sliding-window rate limiter backed by Redis Sorted Sets (ZSET) and Lua.

    Unlike fixed-window counters or TTL resets, this algorithm tracks timestamps
    in a rolling window: requests outside the window expire naturally without penalizing
    intermittent requests, exactly matching the in-memory algorithm.
    """

    def __init__(
        self,
        redis_client,
        max_attempts: int = 60,
        window_seconds: float = 60.0,
        key_prefix: str = "ratelimit",
    ) -> None:
        super().__init__(max_attempts=max_attempts, window_seconds=window_seconds)
        self._redis = redis_client
        self._prefix = key_prefix
        # Register Lua script for atomic sliding window evaluation
        try:
            self._script = self._redis.register_script(_SLIDING_WINDOW_LUA)
        except Exception:
            self._script = None

    @property
    def backend_type(self) -> str:
        return "redis"

    def _key(self, action: str, client_ip: str) -> str:
        return f"{self._prefix}:{action}:{client_ip}"

    def check(
        self,
        action: str,
        client_ip: str,
        max_attempts: int | None = None,
        window_seconds: float | None = None,
    ) -> None:
        limit = max_attempts if max_attempts is not None else self.default_max_attempts
        window = window_seconds if window_seconds is not None else self.default_window_seconds
        key = self._key(action, client_ip)
        now = time.time()
        member = f"{now}:{uuid.uuid4().hex[:8]}"

        if self._script is not None:
            # Atomic Lua evaluation
            allowed = self._script(keys=[key], args=[now, window, limit, member])
        else:
            # Fallback Redis pipeline with ZREMRANGEBYSCORE + ZCARD + ZADD
            pipe = self._redis.pipeline()
            pipe.zremrangebyscore(key, "-inf", now - window)
            pipe.zcard(key)
            results = pipe.execute()
            current_count = results[1]
            if current_count >= limit:
                allowed = 0
            else:
                pipe2 = self._redis.pipeline()
                pipe2.zadd(key, {member: now})
                pipe2.expire(key, int(window) + 1)
                pipe2.execute()
                allowed = 1

        if allowed == 0:
            raise RateLimitExceeded(
                f"Too many '{action}' attempts from {client_ip}. "
                f"Please wait {int(window)} seconds before retrying."
            )

    def reset(self, action: str | None = None, client_ip: str | None = None) -> None:
        if action is None and client_ip is None:
            cursor = 0
            while True:
                cursor, keys = self._redis.scan(cursor, match=f"{self._prefix}:*", count=200)
                if keys:
                    self._redis.delete(*keys)
                if cursor == 0:
                    break
        else:
            pattern = f"{self._prefix}:"
            pattern += f"{action if action is not None else '*'}:"
            pattern += f"{client_ip if client_ip is not None else '*'}"
            cursor = 0
            while True:
                cursor, keys = self._redis.scan(cursor, match=pattern, count=200)
                if keys:
                    self._redis.delete(*keys)
                if cursor == 0:
                    break


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_rate_limiter(
    settings: "Settings",
    max_attempts: int = 60,
    window_seconds: float = 60.0,
) -> RateLimiter:
    """Return the configured rate limiter backend.

    In production:
    - If ``REDIS_URL`` is configured and connection fails, raises ``RuntimeError`` immediately.
    - If ``require_redis_in_production`` is True and ``REDIS_URL`` is empty, raises ``ValueError``.
    - Never silently falls back to in-memory in production when Redis was expected.

    In development:
    - Tries Redis if ``REDIS_URL`` is set; on failure, falls back to in-memory with a warning.
    - Uses in-memory backend when ``REDIS_URL`` is not provided.
    """
    is_production = settings.environment.lower() == "production"
    redis_url = (settings.redis_url or "").strip()

    if is_production and settings.require_redis_in_production and not redis_url:
        raise ValueError(
            "CRITICAL SECURITY CONFIGURATION ERROR: require_redis_in_production is enabled, but REDIS_URL is not set."
        )

    if redis_url:
        try:
            import redis as redis_lib  # type: ignore[import]

            client = redis_lib.from_url(
                redis_url,
                socket_connect_timeout=2,
                socket_timeout=2,
                decode_responses=False,
            )
            client.ping()
            limiter: RateLimiter = RedisRateLimiter(
                redis_client=client,
                max_attempts=max_attempts,
                window_seconds=window_seconds,
            )
            logger.info("Rate limiter: active backend is REDIS (%s)", redis_url)
            return limiter
        except Exception as exc:  # noqa: BLE001
            if is_production:
                # Do NOT silently downgrade in production!
                raise RuntimeError(
                    f"CRITICAL SECURITY ERROR: Production Redis rate-limiter connection failed: {exc}. "
                    "Startup aborted to prevent silent fallback and rate-limit bypass in multi-instance production."
                ) from exc
            logger.warning(
                "Rate limiter: Redis unavailable (%s). Falling back to in-memory backend for local development.",
                exc,
            )

    logger.info("Rate limiter: active backend is IN-MEMORY (single-process dev only).")
    return InMemoryRateLimiter(max_attempts=max_attempts, window_seconds=window_seconds)
