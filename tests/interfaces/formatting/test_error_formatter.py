"""
Unit tests for `parika.interfaces.formatting.error_formatter`.
"""

from __future__ import annotations

from parika.interfaces.formatting.error_formatter import (
    format_error,
    format_exception,
)


class TestFormatError:
    def test_prefixes_message(self) -> None:
        assert format_error("network unreachable") == (
            "Error: network unreachable"
        )


class TestFormatException:
    def test_includes_exception_type_name(self) -> None:
        result = format_exception(RuntimeError("boom"))

        assert "RuntimeError" in result
        assert "boom" in result
