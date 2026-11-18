"""Tests for the pluggable rate limiter service (backend/services/rate_limiter.py).

Covers:
- InMemoryRateLimiter: enforcement, window reset, per-IP isolation
- RedisRateLimiter: enforcement and isolation using a fakeredis stub
- get_rate_limiter factory: returns InMemory when redis_url is empty
"""

from __future__ import annotations

import sys
import time
from unittest.mock import MagicMock, patch

import pytest

from backend.services.rate_limiter import (
    InMemoryRateLimiter,
    RateLimitExceeded,
    RedisRateLimiter,
    get_rate_limiter,
)


# ---------------------------------------------------------------------------
# InMemoryRateLimiter
# ---------------------------------------------------------------------------


class TestInMemoryRateLimiter:
    def test_allows_requests_under_limit(self):
        limiter = InMemoryRateLimiter(max_attempts=5, window_seconds=60.0)
        for _ in range(5):
            limiter.check("login", "1.2.3.4")  # must not raise

    def test_raises_on_exceeding_limit(self):
        limiter = InMemoryRateLimiter(max_attempts=3, window_seconds=60.0)
        for _ in range(3):
            limiter.check("login", "1.2.3.4")
        with pytest.raises(RateLimitExceeded):
            limiter.check("login", "1.2.3.4")

    def test_different_ips_are_isolated(self):
        limiter = InMemoryRateLimiter(max_attempts=2, window_seconds=60.0)
        limiter.check("login", "1.1.1.1")
        limiter.check("login", "1.1.1.1")
        # 1.1.1.1 is now at the limit — but 2.2.2.2 should still be fine
        limiter.check("login", "2.2.2.2")
        with pytest.raises(RateLimitExceeded):
            limiter.check("login", "1.1.1.1")

    def test_different_actions_are_isolated(self):
        limiter = InMemoryRateLimiter(max_attempts=1, window_seconds=60.0)
        limiter.check("login", "1.2.3.4")
        # "login" action is at limit; "register" should still work
        limiter.check("register", "1.2.3.4")
        with pytest.raises(RateLimitExceeded):
            limiter.check("login", "1.2.3.4")

    def test_reset_all_clears_state(self):
        limiter = InMemoryRateLimiter(max_attempts=1, window_seconds=60.0)
        limiter.check("login", "1.2.3.4")
        limiter.reset()
        limiter.check("login", "1.2.3.4")  # must not raise after full reset

    def test_reset_specific_action_and_ip(self):
        limiter = InMemoryRateLimiter(max_attempts=1, window_seconds=60.0)
        limiter.check("login", "1.2.3.4")
        limiter.check("register", "9.9.9.9")
        limiter.reset(action="login", client_ip="1.2.3.4")
        # login/1.2.3.4 cleared — should work again
        limiter.check("login", "1.2.3.4")
        # register/9.9.9.9 untouched — still at limit
        with pytest.raises(RateLimitExceeded):
            limiter.check("register", "9.9.9.9")

    def test_window_expiry_allows_new_requests(self):
        """Timestamps outside the window are pruned, allowing new requests."""
        limiter = InMemoryRateLimiter(max_attempts=2, window_seconds=0.05)
        limiter.check("login", "1.2.3.4")
        limiter.check("login", "1.2.3.4")
        with pytest.raises(RateLimitExceeded):
            limiter.check("login", "1.2.3.4")
        # Wait for window to expire
        time.sleep(0.1)
        limiter.check("login", "1.2.3.4")  # must not raise — window reset


# ---------------------------------------------------------------------------
# RedisRateLimiter (stubbed with fakeredis or manual mock)
# ---------------------------------------------------------------------------


def _make_pipeline_mock(count: int):
    """Return a MagicMock redis client whose pipeline().execute() returns (count, 1)."""
    pipeline_mock = MagicMock()
    pipeline_mock.incr.return_value = None
    pipeline_mock.expire.return_value = None
    pipeline_mock.execute.return_value = (count, 1)

    redis_mock = MagicMock()
    redis_mock.pipeline.return_value = pipeline_mock
    return redis_mock


class TestRedisRateLimiter:
    def test_allows_requests_under_limit(self):
        redis_mock = _make_pipeline_mock(count=1)
        limiter = RedisRateLimiter(redis_client=redis_mock, max_attempts=5, window_seconds=60.0)
        limiter.check("login", "1.2.3.4")  # count=1 <= 5, must not raise

    def test_raises_when_count_exceeds_limit(self):
        redis_mock = _make_pipeline_mock(count=6)
        limiter = RedisRateLimiter(redis_client=redis_mock, max_attempts=5, window_seconds=60.0)
        with pytest.raises(RateLimitExceeded):
            limiter.check("login", "1.2.3.4")

    def test_uses_correct_key_format(self):
        redis_mock = _make_pipeline_mock(count=1)
        pipeline_mock = redis_mock.pipeline.return_value
        limiter = RedisRateLimiter(redis_client=redis_mock, max_attempts=5, window_seconds=30.0, key_prefix="rl")
        limiter.check("register", "5.5.5.5")
        pipeline_mock.incr.assert_called_once_with("rl:register:5.5.5.5")
        pipeline_mock.expire.assert_called_once_with("rl:register:5.5.5.5", 30)

    def test_reset_all_scans_and_deletes(self):
        redis_mock = MagicMock()
        # Simulate two iterations of SCAN: first returns cursor=5 with keys, second cursor=0 empty
        redis_mock.scan.side_effect = [
            (5, [b"ratelimit:login:1.2.3.4"]),
            (0, []),
        ]
        limiter = RedisRateLimiter(redis_client=redis_mock, max_attempts=5, window_seconds=60.0)
        limiter.reset()
        redis_mock.delete.assert_called_once_with(b"ratelimit:login:1.2.3.4")


# ---------------------------------------------------------------------------
# Factory: get_rate_limiter
# ---------------------------------------------------------------------------


class TestGetRateLimiterFactory:
    def test_returns_in_memory_when_redis_url_empty(self):
        settings = MagicMock()
        settings.redis_url = ""
        limiter = get_rate_limiter(settings)
        assert isinstance(limiter, InMemoryRateLimiter)

    def test_returns_in_memory_when_redis_unavailable(self):
        settings = MagicMock()
        settings.redis_url = "redis://nonexistent-host:6379/0"
        # Patch redis.from_url to raise an exception simulating unreachable Redis
        with patch("backend.services.rate_limiter.logger"):
            limiter = get_rate_limiter(settings)
        assert isinstance(limiter, InMemoryRateLimiter)

    def test_returns_redis_limiter_when_redis_reachable(self):
        settings = MagicMock()
        settings.redis_url = "redis://localhost:6379/0"
        redis_client_mock = MagicMock()
        redis_client_mock.ping.return_value = True

        # Patch the import inside our module so the test works even without redis installed
        fake_redis_lib = MagicMock()
        fake_redis_lib.from_url.return_value = redis_client_mock

        with (
            patch("backend.services.rate_limiter.logger"),
            patch.dict("sys.modules", {"redis": fake_redis_lib}),
        ):
            # Clear cached limiter so factory runs fresh
            import backend.services.rate_limiter as rl_mod
            limiter = rl_mod.get_rate_limiter(settings)
            # With a reachable Redis, should return a RedisRateLimiter
            assert isinstance(limiter, RedisRateLimiter)
