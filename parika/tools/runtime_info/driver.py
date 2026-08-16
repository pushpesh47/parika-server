"""
PARIKA Runtime Info Tool - Driver

Implements the `ToolDriver` contract
(`parika.core.tool_manager.driver.ToolDriver`) for deterministic
runtime/system information: the current date and time, optionally in
a specific timezone.

This tool exists specifically so PARIKA never has to rely on an LLM's
own (frequently stale or hallucinated) notion of "now". It performs no
network access and calls no AI provider - it reads the system clock
via the standard library `datetime`/`zoneinfo` modules only.
"""

from __future__ import annotations

from datetime import datetime

from parika.core.tool_manager.request import ToolRequest
from parika.core.tool_manager.response import ToolResponse

from .timezones import resolve_timezone


class RuntimeInfoToolDriver:
    """
    ToolDriver implementation providing the current date/time.
    """

    def execute(self, request: ToolRequest) -> ToolResponse:
        """
        Return the current date and time.

        Args:
            request:
                May supply an optional `"timezone"` argument (an IANA
                name like `"Asia/Kolkata"`, or a supported
                abbreviation like `"IST"`/`"UTC"`). Defaults to UTC
                when omitted.

        Returns:
            A `ToolResponse` whose `result` is a dict with `date`,
            `time`, `weekday`, `timezone`, `utc_offset`, and
            `iso_datetime` keys.

        Raises:
            UnknownTimezoneError:
                If the supplied timezone cannot be resolved.
        """

        timezone_argument = request.arguments.get("timezone")
        zone = resolve_timezone(
            timezone_argument if isinstance(timezone_argument, str) else None
        )

        now = datetime.now(zone)

        result = {
            "date": now.date().isoformat(),
            "time": now.time().isoformat(timespec="seconds"),
            "weekday": now.strftime("%A"),
            "timezone": str(zone),
            "utc_offset": now.strftime("%z"),
            "iso_datetime": now.isoformat(timespec="seconds"),
        }

        return ToolResponse(
            result=result,
            attributes={"timezone": str(zone)},
        )
