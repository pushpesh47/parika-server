"""
PARIKA Web Search Tool - Retry Handling

Provides a small, dependency-free retry helper used by the Web Search
Tool when performing network operations.
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

    Args:
        operation:
            Zero-argument callable to invoke.

        max_attempts:
            Maximum number of attempts, including the first. Must be
            at least 1.

        backoff_seconds:
            Base delay, in seconds, between attempts. The delay grows
            linearly with the attempt number
            (`backoff_seconds * attempt_number`).

        retryable_exceptions:
            Exception types that should trigger a retry. Any other
            exception propagates immediately.

        sleep:
            Sleep function used between attempts. Injectable so tests
            can avoid real delays.

    Returns:
        The value returned by `operation`.

    Raises:
        Exception:
            The last exception raised by `operation`, if every
            attempt failed, or any non-retryable exception
            immediately.
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
