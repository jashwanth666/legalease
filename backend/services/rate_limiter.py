"""Pluggable sliding-window rate limiter with Redis (distributed) and in-memory (dev) backends.

Usage
-----
Call ``get_rate_limiter(settings)`` once at module load to obtain the shared
limiter instance.  Then call ``limiter.check(action, client_ip)`` on every
sensitive request; it raises ``RateLimitExceeded`` when the caller is over the
configured limit.

For testing, call ``limiter.reset()`` to clear all windows.
"""

from __future__ import annotations

import logging
import threading
import time
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
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds

    @abstractmethod
    def check(self, action: str, client_ip: str) -> None:
        """Record a hit and raise ``RateLimitExceeded`` if the limit is exceeded.

        Args:
            action: Logical endpoint key (e.g. ``"login"``, ``"register"``).
            client_ip: Client IP address string from the request.

        Raises:
            RateLimitExceeded: When the caller has made too many attempts.
        """

    @abstractmethod
    def reset(self, action: str | None = None, client_ip: str | None = None) -> None:
        """Clear rate-limit windows.

        Args:
            action: If provided, only clear windows for this action.
            client_ip: If provided, only clear windows for this IP.
            When both are ``None`` all state is cleared (useful in tests).
        """


# ---------------------------------------------------------------------------
# In-memory backend (dev / single-process)
# ---------------------------------------------------------------------------


@dataclass
class InMemoryRateLimiter(RateLimiter):
    """Thread-safe sliding-window in-memory rate limiter.

    Tracks each ``"{action}:{ip}"`` key independently.  State is local to the
    process, so it is NOT shared across multiple worker instances.
    """

    _lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _windows: dict[str, list[float]] = field(default_factory=dict, init=False, repr=False)

    def __init__(self, max_attempts: int = 60, window_seconds: float = 60.0) -> None:
        super().__init__(max_attempts=max_attempts, window_seconds=window_seconds)
        self._lock = threading.Lock()
        self._windows: dict[str, list[float]] = {}

    def _key(self, action: str, client_ip: str) -> str:
        return f"{action}:{client_ip}"

    def check(self, action: str, client_ip: str) -> None:
        key = self._key(action, client_ip)
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            timestamps = [t for t in self._windows.get(key, []) if t >= cutoff]
            if len(timestamps) >= self.max_attempts:
                self._windows[key] = timestamps  # keep pruned list without adding
                raise RateLimitExceeded(
                    f"Too many '{action}' attempts from {client_ip}. "
                    f"Please wait {int(self.window_seconds)} seconds before retrying."
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
# Redis backend (production / distributed)
# ---------------------------------------------------------------------------


class RedisRateLimiter(RateLimiter):
    """Distributed sliding-window rate limiter backed by Redis INCR + EXPIRE.

    Uses a fixed-window counter per ``"{action}:{ip}"`` key.  When a window
    expires Redis removes the key automatically, so no background cleanup is
    needed.

    Args:
        redis_client: A connected ``redis.Redis`` client instance.
        max_attempts: Maximum allowed requests within the window.
        window_seconds: Length of the sliding window in seconds (integer).
        key_prefix: Optional prefix prepended to all Redis keys.
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

    def _key(self, action: str, client_ip: str) -> str:
        return f"{self._prefix}:{action}:{client_ip}"

    def check(self, action: str, client_ip: str) -> None:
        key = self._key(action, client_ip)
        pipeline = self._redis.pipeline()
        pipeline.incr(key)
        pipeline.expire(key, int(self.window_seconds))
        count, _ = pipeline.execute()
        if count > self.max_attempts:
            raise RateLimitExceeded(
                f"Too many '{action}' attempts from {client_ip}. "
                f"Please wait {int(self.window_seconds)} seconds before retrying."
            )

    def reset(self, action: str | None = None, client_ip: str | None = None) -> None:
        if action is None and client_ip is None:
            # Flush all keys with our prefix (use SCAN for large key-spaces)
            cursor = 0
            while True:
                cursor, keys = self._redis.scan(cursor, match=f"{self._prefix}:*", count=200)
                if keys:
                    self._redis.delete(*keys)
                if cursor == 0:
                    break
        else:
            suffix = ""
            if action is not None:
                suffix += f":{action}"
            else:
                suffix += ":*"
            if client_ip is not None:
                suffix += f":{client_ip}"
            else:
                suffix += ":*"
            pattern = f"{self._prefix}{suffix}"
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


def get_rate_limiter(settings: "Settings", max_attempts: int = 60, window_seconds: float = 60.0) -> RateLimiter:
    """Return the best available rate limiter.

    Attempts to connect to Redis when ``settings.redis_url`` is non-empty.
    Falls back to the in-memory backend silently if Redis is unreachable or
    not configured, so local development works without any extra services.

    Args:
        settings: Application settings (read ``redis_url``).
        max_attempts: Maximum allowed requests within the window.
        window_seconds: Sliding window length in seconds.

    Returns:
        A connected ``RedisRateLimiter`` or ``InMemoryRateLimiter``.
    """
    redis_url = (settings.redis_url or "").strip()
    if redis_url:
        try:
            import redis as redis_lib  # type: ignore[import]

            client = redis_lib.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2, decode_responses=False)
            client.ping()
            limiter: RateLimiter = RedisRateLimiter(
                redis_client=client,
                max_attempts=max_attempts,
                window_seconds=window_seconds,
            )
            logger.info("Rate limiter: using Redis backend at %s", redis_url)
            return limiter
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Rate limiter: Redis unavailable (%s). Falling back to in-memory backend. "
                "This is acceptable for single-instance dev; configure Redis for production multi-instance deployments.",
                exc,
            )

    logger.info("Rate limiter: using in-memory backend (single-process only).")
    return InMemoryRateLimiter(max_attempts=max_attempts, window_seconds=window_seconds)
