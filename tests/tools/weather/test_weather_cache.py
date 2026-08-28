"""
Unit tests for PostgreSQLWeatherCache.
"""


from __future__ import annotations
from tests.conftest_db import build_test_db_config

import asyncio
import pytest

from parika.tools.weather.postgresql_cache import PostgreSQLWeatherCache, make_cache_key
from parika.core.database.pool import PoolManager
import parika.core.database.config as db_config_module
from parika.core.database.config import DatabaseConfig


# Test database configuration
# Test database configuration from environment
# TEST_DATABASE_CONFIG = { ... }  # Replaced by build_test_db_config()


@pytest.fixture(scope="session")
def _test_db_pool():
    """Initialize PostgreSQL test pool for the test session."""
    db_config = build_test_db_config()
    pool = PoolManager.initialize_sync_pool(db_config)
    yield pool
    PoolManager.shutdown_sync_pool()


@pytest.fixture()
def cache(_test_db_pool) -> PostgreSQLWeatherCache:
    cache = PostgreSQLWeatherCache(_test_db_pool, ttl_seconds=0.1, max_entries=2)
    cache.initialize()

    yield cache

    cache.shutdown()


class TestMakeCacheKey:
    def test_normalizes_to_4_decimal_places(self):
        key = make_cache_key(12.9715987, 77.5945667)
        assert key == "12.9716:77.5946"

    def test_different_locations_different_keys(self):
        key1 = make_cache_key(12.9716, 77.5946)
        key2 = make_cache_key(28.6139, 77.2090)
        assert key1 != key2

    def test_same_location_same_key(self):
        key1 = make_cache_key(12.9716, 77.5946)
        key2 = make_cache_key(12.97159, 77.59456)
        assert key1 == key2


class TestPostgreSQLWeatherCache:
    def test_postgresql_persistence(self, cache: PostgreSQLWeatherCache):
        key = "persist:key"
        data = {"temperature": 25, "humidity": 60}

        cache.set(key, data)

        # Create new cache instance with same pool
        cache2 = PostgreSQLWeatherCache(cache._pool, ttl_seconds=60)
        cache2.initialize()

        try:
            result = cache2.get_cached(key)
            assert result is not None
            cached_data, _ = result
            assert cached_data == data
        finally:
            cache2.shutdown()

    def test_max_entries_eviction(self, _test_db_pool):
        cache = PostgreSQLWeatherCache(_test_db_pool, ttl_seconds=60, max_entries=2)
        cache.initialize()

        try:
            cache.set("key1", {"temp": 1})
            cache.set("key2", {"temp": 2})
            cache.set("key3", {"temp": 3})  # Should evict key1

            assert cache.get_cached("key1") is None
            assert cache.get_cached("key2") is not None
            assert cache.get_cached("key3") is not None
        finally:
            cache.shutdown()

    def test_get_or_fetch_fresh(self, cache: PostgreSQLWeatherCache):
        call_count = 0

        async def fetch_func():
            nonlocal call_count
            call_count += 1
            return {"fetched": call_count}

        async def run_test():
            data1, status1 = await cache.get_or_fetch("key1", fetch_func)
            data2, status2 = await cache.get_or_fetch("key1", fetch_func)

            assert data1 == data2 == {"fetched": 1}
            assert status1 == "fetched"
            assert status2 == "fresh"
            assert call_count == 1

        asyncio.run(run_test())

    def test_get_or_fetch_stampede_prevention(self, cache: PostgreSQLWeatherCache):
        """Test that concurrent requests after expiry only trigger one fetch."""
        call_count = 0

        async def fetch_func():
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)  # Simulate network delay
            return {"fetched": call_count}

        async def run_test():
            # Pre-populate cache with expired data
            cache.set("key1", {"fetched": 0})
            await asyncio.sleep(0.2)  # Wait for cache to expire

            # Launch multiple concurrent requests
            results = await asyncio.gather(*[
                cache.get_or_fetch("key1", fetch_func)
                for _ in range(5)
            ])

            # All should return the same data
            data_values = [r[0] for r in results]
            assert all(d == data_values[0] for d in data_values)
            # Fetch should only be called once (stampede prevention)
            assert call_count == 1
            # First request gets "fetched", others get "fresh" (after first fetch completes)
            statuses = [r[1] for r in results]
            assert "fetched" in statuses
            assert all(s in ("fetched", "fresh") for s in statuses)

        asyncio.run(run_test())
