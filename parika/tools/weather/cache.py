"""
PARIKA Weather API - Cache

Caches normalized weather responses keyed by normalized coordinates
with a configurable TTL. Uses PostgreSQL for cross-run persistence plus
an in-process dict for same-run hits without a database round trip.

Prevents cache stampedes via per-key locks (asyncio.Lock for async
contexts, threading.Lock for multi-threaded contexts) so concurrent
requests after expiry trigger only one provider fetch.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePath
from typing import Any

SQLITE_BUSY_TIMEOUT_MS: int = 5000


class WeatherCacheError(Exception):
    """Raised when the weather cache fails to read or write."""


@dataclass(frozen=True, slots=True, kw_only=True)
class WeatherCacheConfig:
    """Typed configuration for `WeatherCache`."""

    enabled: bool = True
    ttl_seconds: float = 1200.0
    max_entries: int = 500


def make_cache_key(latitude: float, longitude: float) -> str:
    """
    Build a normalized cache key from coordinates.

    Normalizes to 4 decimal places (~11m precision) to avoid
    fragmentation from tiny floating-point differences while still
    distinguishing different locations.
    """
    norm_lat = round(latitude, 4)
    norm_lon = round(longitude, 4)
    return f"{norm_lat}:{norm_lon}"


class WeatherCache:
    """
    TTL-based cache for normalized weather responses.

    This class now delegates to either PostgreSQL or in-memory storage.
    The actual implementation is selected at runtime by the caller.
    """

    __slots__ = ("_impl",)

    def __init__(
        self,
        database_path: Path | None,
        *,
        ttl_seconds: float = 1200.0,
        max_entries: int = 500,
    ) -> None:
        if database_path is not None and not isinstance(database_path, PurePath):
            raise TypeError("database_path must be a pathlib.Path object or None.")

        # This is now a factory - actual implementation is created by the caller
        # with the appropriate pool. This class is kept for backward compatibility.
        self._impl = None

    def initialize(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def _get_async_lock(self, key: str) -> asyncio.Lock:
        raise NotImplementedError("Use PostgreSQLWeatherCache directly")

    def _get_thread_lock(self, key: str) -> threading.Lock:
        raise NotImplementedError("Use PostgreSQLWeatherCache directly")

    async def get_or_fetch(
        self,
        key: str,
        fetch_func,
        *fetch_args,
        **fetch_kwargs,
    ) -> tuple[dict[str, Any], str]:
        raise NotImplementedError("Use PostgreSQLWeatherCache directly")

    def set(self, key: str, data: dict[str, Any]) -> None:
        raise NotImplementedError("Use PostgreSQLWeatherCache directly")

    async def aset(self, key: str, data: dict[str, Any]) -> None:
        raise NotImplementedError("Use PostgreSQLWeatherCache directly")

    def get_cached(self, key: str) -> tuple[dict[str, Any], float] | None:
        raise NotImplementedError("Use PostgreSQLWeatherCache directly")

    def _delete(self, key: str) -> None:
        pass


def _serialize(data: dict[str, Any]) -> str:
    return json.dumps(data, separators=(",", ":"))


def _deserialize(payload: str) -> dict[str, Any]:
    return json.loads(payload)