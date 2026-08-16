"""
PARIKA Runtime Info Tool - Timezone Resolution

Resolves a user-supplied timezone name - an IANA name (e.g.
`"Asia/Kolkata"`) or a common abbreviation (e.g. `"IST"`, `"UTC"`) -
into a `zoneinfo.ZoneInfo` instance, using only the standard library.

Common abbreviations are ambiguous in general (`"IST"` can mean India,
Ireland, or Israel Standard Time depending on context); this module
resolves each supported abbreviation to a single, documented IANA
zone, favoring the most common real-world usage.
"""

from __future__ import annotations

from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .exceptions import UnknownTimezoneError

_ABBREVIATION_TO_IANA: dict[str, str] = {
    "UTC": "UTC",
    "GMT": "UTC",
    "IST": "Asia/Kolkata",
    "EST": "America/New_York",
    "EDT": "America/New_York",
    "CST": "America/Chicago",
    "CDT": "America/Chicago",
    "MST": "America/Denver",
    "MDT": "America/Denver",
    "PST": "America/Los_Angeles",
    "PDT": "America/Los_Angeles",
    "BST": "Europe/London",
    "CET": "Europe/Paris",
    "JST": "Asia/Tokyo",
    "AEST": "Australia/Sydney",
}
"""
Common timezone abbreviations mapped to a single, representative IANA
zone. Not exhaustive; callers wanting an unambiguous result should
supply a full IANA name instead.
"""


def resolve_timezone(name: str | None) -> ZoneInfo:
    """
    Resolve a timezone name or abbreviation to a `ZoneInfo`.

    Args:
        name:
            An IANA timezone name (e.g. `"Asia/Kolkata"`), a supported
            abbreviation (e.g. `"IST"`), or `None`/empty for UTC.

    Returns:
        The resolved `ZoneInfo`.

    Raises:
        UnknownTimezoneError:
            If `name` is neither a supported abbreviation nor a valid
            IANA timezone name.
    """

    if not name or not name.strip():
        return ZoneInfo("UTC")

    candidate = name.strip()
    iana_name = _ABBREVIATION_TO_IANA.get(candidate.upper(), candidate)

    try:
        return ZoneInfo(iana_name)
    except (ZoneInfoNotFoundError, ValueError) as ex:
        raise UnknownTimezoneError(
            f"Unknown timezone '{name}'. Use an IANA timezone name "
            "(e.g. 'Asia/Kolkata') or one of the supported "
            f"abbreviations: {', '.join(sorted(_ABBREVIATION_TO_IANA))}."
        ) from ex
