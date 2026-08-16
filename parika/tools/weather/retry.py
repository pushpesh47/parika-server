"""
PARIKA Weather Tool - Retry Handling

A small, dependency-free retry helper used by the Weather Tool when
performing network operations. Mirrors
`parika/tools/web_search/retry.py`'s pattern exactly, kept as this
Tool's own independent module per the project's convention of
self-contained Tool packages.
"""

from __future__ import annotations

from collections.abc import Callable
from time import sleep as time_sleep
from typing import TypeVar

T = TypeVar("T")


def retry_with_backoff(
    operation: Callable[[], T],
    *,
    max_attempts: int,
    backoff_seconds: float,
    retryable_exceptions: tuple[type[Exception], ...],
    sleep: Callable[[float], None] = time_sleep,
) -> T:
    """
    Invoke `operation`, retrying on retryable failures using linear
    backoff.
    """

    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1.")

    last_exception: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            return operation()

        except retryable_exceptions as ex:
            last_exception = ex

            if attempt == max_attempts:
                break

            sleep(backoff_seconds * attempt)

    assert last_exception is not None
    raise last_exception
