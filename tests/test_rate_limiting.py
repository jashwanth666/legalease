"""Tests for the pluggable rate limiter service (backend/services/rate_limiter.py).

Covers:
- InMemoryRateLimiter: enforcement, rolling window prune, per-IP and per-action isolation
- RedisRateLimiter: true sliding-window Lua execution, pipeline fallback, over-limit raising
- Production fail-closed behavior: raises on Redis outage in production (no silent downgrade)
- Factory behavior in dev vs. production environments
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
        assert limiter.backend_type == "inmemory"
        for _ in range(5):
            limiter.check("login", "1.2.3.4")

    def test_raises_on_exceeding_limit(self):
        limiter = InMemoryRateLimiter(max_attempts=3, window_seconds=60.0)
        for _ in range(3):
            limiter.check("login", "1.2.3.4")
        with pytest.raises(RateLimitExceeded):
            limiter.check("login", "1.2.3.4")

    def test_custom_endpoint_specific_limits(self):
        """Endpoints can pass custom max_attempts (e.g. bootstrap=10, login=30)."""
        limiter = InMemoryRateLimiter(max_attempts=60, window_seconds=60.0)
        # Limit of 2 for this check
        limiter.check("bootstrap", "1.2.3.4", max_attempts=2)
        limiter.check("bootstrap", "1.2.3.4", max_attempts=2)
        with pytest.raises(RateLimitExceeded):
            limiter.check("bootstrap", "1.2.3.4", max_attempts=2)

    def test_different_ips_are_isolated(self):
        limiter = InMemoryRateLimiter(max_attempts=2, window_seconds=60.0)
        limiter.check("login", "1.1.1.1")
        limiter.check("login", "1.1.1.1")
        # 1.1.1.1 is now at the limit — but 2.2.2.2 should still be permitted
        limiter.check("login", "2.2.2.2")
        with pytest.raises(RateLimitExceeded):
            limiter.check("login", "1.1.1.1")

    def test_different_actions_are_isolated(self):
        """Actions (bootstrap, register, login) must maintain separate quotas."""
        limiter = InMemoryRateLimiter(max_attempts=1, window_seconds=60.0)
        limiter.check("login", "1.2.3.4")
        # "login" action is exhausted; "register" and "bootstrap" must still be permitted
        limiter.check("register", "1.2.3.4")
        limiter.check("bootstrap", "1.2.3.4")
        with pytest.raises(RateLimitExceeded):
            limiter.check("login", "1.2.3.4")

    def test_reset_all_clears_state(self):
        limiter = InMemoryRateLimiter(max_attempts=1, window_seconds=60.0)
        limiter.check("login", "1.2.3.4")
        limiter.reset()
        limiter.check("login", "1.2.3.4")

    def test_window_expiry_allows_new_requests(self):
        limiter = InMemoryRateLimiter(max_attempts=2, window_seconds=0.05)
        limiter.check("login", "1.2.3.4")
        limiter.check("login", "1.2.3.4")
        with pytest.raises(RateLimitExceeded):
            limiter.check("login", "1.2.3.4")
        # Wait for rolling window to expire
        time.sleep(0.08)
        limiter.check("login", "1.2.3.4")  # must not raise


# ---------------------------------------------------------------------------
# RedisRateLimiter (True sliding-window Lua and Pipeline)
# ---------------------------------------------------------------------------


class TestRedisRateLimiter:
    def test_allows_requests_when_lua_returns_1(self):
        redis_mock = MagicMock()
        script_mock = MagicMock()
        script_mock.return_value = 1  # Allowed
        redis_mock.register_script.return_value = script_mock

        limiter = RedisRateLimiter(redis_client=redis_mock, max_attempts=5, window_seconds=60.0)
        assert limiter.backend_type == "redis"
        limiter.check("login", "1.2.3.4")
        script_mock.assert_called_once()
        args = script_mock.call_args[1]["args"]
        assert args[1] == 60.0  # window
        assert args[2] == 5     # limit

    def test_raises_when_lua_returns_0(self):
        redis_mock = MagicMock()
        script_mock = MagicMock()
        script_mock.return_value = 0  # Denied
        redis_mock.register_script.return_value = script_mock

        limiter = RedisRateLimiter(redis_client=redis_mock, max_attempts=5, window_seconds=60.0)
        with pytest.raises(RateLimitExceeded):
            limiter.check("login", "1.2.3.4")

    def test_direct_eval_fallback_is_atomic(self):
        """When register_script fails, fallback uses atomic redis.eval with full 128-bit UUID."""
        redis_mock = MagicMock()
        redis_mock.register_script.side_effect = Exception("No script cache")
        redis_mock.eval.return_value = 1  # Allowed

        limiter = RedisRateLimiter(redis_client=redis_mock, max_attempts=3, window_seconds=60.0)
        assert limiter._script is None
        limiter.check("register", "9.9.9.9")
        redis_mock.eval.assert_called_once()
        # Verify member parameter contains full 32-hex character UUID
        args = redis_mock.eval.call_args[0]
        member = args[6]  # _SLIDING_WINDOW_LUA, 1, key, now, window, limit, member
        _, uuid_part = member.split(":", 1)
        assert len(uuid_part) == 32

        # When eval returns 0 (limit reached)
        redis_mock.eval.return_value = 0
        with pytest.raises(RateLimitExceeded):
            limiter.check("register", "9.9.9.9")

    def test_reset_all_scans_and_deletes(self):
        redis_mock = MagicMock()
        redis_mock.scan.side_effect = [
            (5, [b"ratelimit:login:1.2.3.4"]),
            (0, []),
        ]
        limiter = RedisRateLimiter(redis_client=redis_mock, max_attempts=5, window_seconds=60.0)
        limiter.reset()
        redis_mock.delete.assert_called_once_with(b"ratelimit:login:1.2.3.4")


# ---------------------------------------------------------------------------
# Factory: get_rate_limiter & Production Fail-Closed Security
# ---------------------------------------------------------------------------


class TestGetRateLimiterFactory:
    def test_dev_falls_back_to_in_memory_when_redis_url_empty(self):
        settings = MagicMock()
        settings.environment = "development"
        settings.redis_url = ""
        limiter = get_rate_limiter(settings)
        assert isinstance(limiter, InMemoryRateLimiter)
        assert limiter.backend_type == "inmemory"

    def test_dev_falls_back_to_in_memory_when_redis_unavailable(self):
        settings = MagicMock()
        settings.environment = "development"
        settings.redis_url = "redis://nonexistent-host:6379/0"
        with patch("backend.services.rate_limiter.logger"):
            limiter = get_rate_limiter(settings)
        assert isinstance(limiter, InMemoryRateLimiter)

    def test_prod_raises_runtime_error_when_redis_fails(self):
        """In production, Redis failure must FAIL FAST rather than silently downgrading security."""
        settings = MagicMock()
        settings.environment = "production"
        settings.redis_url = "redis://unreachable-redis:6379/0"
        settings.require_redis_in_production = False

        fake_redis_lib = MagicMock()
        fake_redis_lib.from_url.side_effect = Exception("Connection refused")

        with (
            patch.dict("sys.modules", {"redis": fake_redis_lib}),
            pytest.raises(RuntimeError, match="CRITICAL SECURITY ERROR: Production Redis rate-limiter connection failed"),
        ):
            get_rate_limiter(settings)

    def test_prod_raises_value_error_by_default_when_redis_url_empty(self):
        """In production by default, empty REDIS_URL must raise ValueError."""
        settings = MagicMock()
        settings.environment = "production"
        settings.redis_url = ""
        settings.allow_inmemory_rate_limiter_in_production = False

        with pytest.raises(ValueError, match="Running in production requires REDIS_URL"):
            get_rate_limiter(settings)

    def test_prod_allows_inmemory_when_explicitly_opted_in(self):
        """In production, allow_inmemory_rate_limiter_in_production=True permits in-memory limiter."""
        settings = MagicMock()
        settings.environment = "production"
        settings.redis_url = ""
        settings.allow_inmemory_rate_limiter_in_production = True

        limiter = get_rate_limiter(settings)
        assert isinstance(limiter, InMemoryRateLimiter)
        assert limiter.backend_type == "inmemory"

    def test_returns_redis_limiter_when_reachable(self):
        settings = MagicMock()
        settings.environment = "development"
        settings.redis_url = "redis://localhost:6379/0"
        redis_client_mock = MagicMock()
        redis_client_mock.ping.return_value = True

        fake_redis_lib = MagicMock()
        fake_redis_lib.from_url.return_value = redis_client_mock

        with (
            patch("backend.services.rate_limiter.logger"),
            patch.dict("sys.modules", {"redis": fake_redis_lib}),
        ):
            import backend.services.rate_limiter as rl_mod
            limiter = rl_mod.get_rate_limiter(settings)
            assert isinstance(limiter, RedisRateLimiter)
            assert limiter.backend_type == "redis"
