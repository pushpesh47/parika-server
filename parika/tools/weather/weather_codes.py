"""
PARIKA Weather Tool - WMO Weather Code Descriptions

Maps the WMO ("World Meteorological Organization") weather codes
returned by Open-Meteo's `weather_code` field to a short, human
readable description, so callers (and any model reading the result)
never have to interpret a raw numeric code themselves.
"""

from __future__ import annotations

WMO_WEATHER_CODES: dict[int, str] = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


def describe_weather_code(code: int | float | None) -> str | None:
    """
    Return a short human-readable description for a WMO weather
    code, or `None` when the code is missing or unrecognized.
    """

    if code is None:
        return None

    return WMO_WEATHER_CODES.get(int(code))
