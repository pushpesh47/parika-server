"""
Unit tests for the Web Search Tool retry helper.
"""

from __future__ import annotations

import pytest

from parika.tools.web_search.retry import retry_with_backoff


class _RetryableError(Exception):
    pass


class _OtherError(Exception):
    pass


class TestRetryWithBackoff:
    def test_returns_result_on_first_success(self) -> None:
        calls: list[int] = []

        def _operation() -> str:
            calls.append(1)
            return "ok"

        result = retry_with_backoff(
            _operation,
            max_attempts=3,
            backoff_seconds=0.01,
            retryable_exceptions=(_RetryableError,),
            sleep=lambda seconds: None,
        )

        assert result == "ok"
        assert len(calls) == 1

    def test_retries_until_success(self) -> None:
        attempts: list[int] = []

        def _operation() -> str:
            attempts.append(1)

            if len(attempts) < 3:
                raise _RetryableError("transient")

            return "recovered"

        sleeps: list[float] = []

        result = retry_with_backoff(
            _operation,
            max_attempts=5,
            backoff_seconds=0.1,
            retryable_exceptions=(_RetryableError,),
            sleep=sleeps.append,
        )

        assert result == "recovered"
        assert len(attempts) == 3
        assert sleeps == [0.1, 0.2]

    def test_raises_last_exception_after_exhausting_attempts(self) -> None:
        def _operation() -> None:
            raise _RetryableError("always fails")

        with pytest.raises(_RetryableError):
            retry_with_backoff(
                _operation,
                max_attempts=3,
                backoff_seconds=0.01,
                retryable_exceptions=(_RetryableError,),
                sleep=lambda seconds: None,
            )

    def test_non_retryable_exception_propagates_immediately(self) -> None:
        calls: list[int] = []

        def _operation() -> None:
            calls.append(1)
            raise _OtherError("fatal")

        with pytest.raises(_OtherError):
            retry_with_backoff(
                _operation,
                max_attempts=5,
                backoff_seconds=0.01,
                retryable_exceptions=(_RetryableError,),
                sleep=lambda seconds: None,
            )

        assert len(calls) == 1

    def test_rejects_non_positive_max_attempts(self) -> None:
        with pytest.raises(ValueError):
            retry_with_backoff(
                lambda: "ok",
                max_attempts=0,
                backoff_seconds=0.01,
                retryable_exceptions=(_RetryableError,),
            )
