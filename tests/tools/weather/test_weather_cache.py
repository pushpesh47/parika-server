"""
Unit tests for WeatherCache.
"""

from __future__ import annotations

import json
import tempfile
import time
from pathlib import Path

import pytest

from parika.tools.weather.cache import WeatherCache, make_cache_key


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


class TestWeatherCache:
    def test_in_memory_cache_hit(self):
        cache = WeatherCache(None, ttl_seconds=60)
        cache.initialize()

        try:
            key = "test:key"
            data = {"temperature": 25}

            cache.set(key, data)
            result = cache.get_cached(key)

            assert result is not None
            cached_data, cached_at = result
            assert cached_data == data
        finally:
            cache.shutdown()

    def test_in_memory_cache_expiry(self):
        cache = WeatherCache(None, ttl_seconds=0.1)
        cache.initialize()

        try:
            key = "test:key"
            data = {"temperature": 25}

            cache.set(key, data)
            time.sleep(0.2)
            result = cache.get_cached(key)

            assert result is None
        finally:
            cache.shutdown()

    def test_sqlite_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "weather_cache.sqlite3"
            cache = WeatherCache(db_path, ttl_seconds=60)
            cache.initialize()

            try:
                key = "persist:key"
                data = {"temperature": 25, "humidity": 60}

                cache.set(key, data)

                # Create new cache instance with same DB
                cache2 = WeatherCache(db_path, ttl_seconds=60)
                cache2.initialize()

                try:
                    result = cache2.get_cached(key)
                    assert result is not None
                    cached_data, _ = result
                    assert cached_data == data
                finally:
                    cache2.shutdown()
            finally:
                cache.shutdown()

    def test_max_entries_eviction(self):
        cache = WeatherCache(None, ttl_seconds=60, max_entries=2)
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

    def test_get_or_fetch_fresh(self):
        cache = WeatherCache(None, ttl_seconds=60)
        cache.initialize()

        try:
            call_count = 0

            async def fetch_func():
                nonlocal call_count
                call_count += 1
                return {"fetched": call_count}

            import asyncio

            async def run_test():
                data1, status1 = await cache.get_or_fetch("key1", fetch_func)
                data2, status2 = await cache.get_or_fetch("key1", fetch_func)

                assert data1 == data2 == {"fetched": 1}
                assert status1 == "fetched"
                assert status2 == "fresh"
                assert call_count == 1

            asyncio.run(run_test())
        finally:
            cache.shutdown()

    def test_get_or_fetch_stampede_prevention(self):
        """Test that concurrent requests after expiry only trigger one fetch."""
        cache = WeatherCache(None, ttl_seconds=0.1)
        cache.initialize()

        try:
            call_count = 0

            async def fetch_func():
                nonlocal call_count
                call_count += 1
                await asyncio.sleep(0.05)  # Simulate network delay
                return {"fetched": call_count}

            import asyncio

            async def run_test():
                # Pre-populate cache with expired data
                cache.set("key1", {"fetched": 0})
                time.sleep(0.2)  # Expire the cache

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
        finally:
            cache.shutdown()


import asyncio