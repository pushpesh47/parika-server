"""
PARIKA Weather Tool - Geocoding

Resolves a free-text location name (e.g. "Bengaluru", "Paris, France")
to geographic coordinates using Open-Meteo's free, keyless Geocoding
API (`https://geocoding-api.open-meteo.com`) - the same no-API-key
provider family as the forecast API itself, so the Weather Tool never
needs a second, differently-licensed geocoding dependency.

Open-Meteo's `name` search matches the text before the first comma
against place names/aliases, treating anything after a comma as an
admin-region/country filter. A comma-free, multi-word location (e.g.
"Patna Bihar", "New York NY") therefore often returns zero results,
even though the equivalent comma-punctuated form ("Patna, Bihar",
"New York, NY") resolves correctly. `geocode()` compensates for this
deterministically: if the caller's exact `location` string returns no
results, it retries with a small, ordered set of comma-inserted
rewrites of that same string - never a different or "corrected" city
name - before giving up. See `_candidate_locations()`.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from .exceptions import LocationNotFoundError, WeatherNetworkError
from .transport import HttpTransport

GEOCODING_ENDPOINT = "https://geocoding-api.open-meteo.com/v1/search"


def reverse_geocode(
    latitude: float,
    longitude: float,
    *,
    transport: HttpTransport,
    timeout_seconds: float,
) -> str | None:
    """
    Resolve coordinates to a human-readable location name using
    Open-Meteo's reverse geocoding.

    Args:
        latitude: Latitude in decimal degrees.
        longitude: Longitude in decimal degrees.
        transport: HttpTransport used to issue the request.
        timeout_seconds: Maximum time, in seconds, to wait for the request.

    Returns:
        Resolved location name (e.g. "Bengaluru, Karnataka, India"), or
        None if reverse geocoding fails or returns no results.
    """
    query_string = urlencode({
        "latitude": latitude,
        "longitude": longitude,
        "count": 1,
        "format": "json",
        "language": "en",
    })
    url = f"{GEOCODING_ENDPOINT}?{query_string}"

    try:
        response = transport.get(url, timeout=timeout_seconds)

        if response.status_code >= 400:
            return None

        payload = json.loads(response.body.decode("utf-8", errors="replace"))
        results = payload.get("results") or []

        if not results:
            return None

        best = results[0]
        name = best.get("name")
        admin1 = best.get("admin1")
        country = best.get("country")

        parts = [name]
        if admin1 and admin1 != name:
            parts.append(admin1)
        if country:
            parts.append(country)

        return ", ".join(parts)

    except Exception:
        # Reverse geocoding is best-effort; never fail the weather request
        return None


@dataclass(frozen=True, slots=True, kw_only=True)
class GeocodeResult:
    """
    Immutable resolved location.
    """

    name: str
    latitude: float
    longitude: float
    country: str | None
    timezone: str | None


def geocode(
    location: str,
    *,
    transport: HttpTransport,
    timeout_seconds: float,
) -> GeocodeResult:
    """
    Resolve a location name to coordinates.

    Tries `location` exactly as given first. Only if that returns no
    results does it retry with the deterministic, comma-inserted
    rewrites produced by `_candidate_locations()` - see that
    function's docstring. The first candidate (in order) that
    resolves to at least one result wins; no ranking or comparison is
    performed across candidates.

    Args:
        location:
            Free-text place name.

        transport:
            HttpTransport used to issue the request.

        timeout_seconds:
            Maximum time, in seconds, to wait for the request.

    Returns:
        The best-matching `GeocodeResult`.

    Raises:
        LocationNotFoundError:
            If no matching location is found for `location` or any
            of its candidate rewrites.

        WeatherNetworkError:
            If the provider returns a malformed response.
    """

    for candidate in _candidate_locations(location):
        results = _lookup(
            candidate, transport=transport, timeout_seconds=timeout_seconds
        )

        if not results:
            continue

        best = results[0]

        try:
            return GeocodeResult(
                name=str(best["name"]),
                latitude=float(best["latitude"]),
                longitude=float(best["longitude"]),
                country=best.get("country"),
                timezone=best.get("timezone"),
            )
        except (KeyError, TypeError, ValueError) as ex:
            raise WeatherNetworkError(
                "Open-Meteo geocoding returned an unexpected result shape."
            ) from ex

    raise LocationNotFoundError(
        f"Could not resolve location '{location}' to coordinates."
    )


def _lookup(
    query: str,
    *,
    transport: HttpTransport,
    timeout_seconds: float,
) -> list[Any]:
    """
    Issue a single geocoding request for `query` and return its
    `results` list (empty when Open-Meteo finds no match).

    Raises:
        WeatherNetworkError:
            If the provider returns an HTTP error or a malformed
            response. Never raised for a merely empty match - that is
            reported to the caller as an empty list, not an
            exception, so `geocode()` can try the next candidate.
    """

    query_string = urlencode({"name": query, "count": 1, "format": "json"})
    url = f"{GEOCODING_ENDPOINT}?{query_string}"

    response = transport.get(url, timeout=timeout_seconds)

    if response.status_code >= 400:
        raise WeatherNetworkError(
            f"Open-Meteo geocoding returned HTTP {response.status_code}."
        )

    try:
        payload = json.loads(response.body.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as ex:
        raise WeatherNetworkError(
            "Open-Meteo geocoding returned a malformed JSON response."
        ) from ex

    return payload.get("results") or []


def _candidate_locations(location: str) -> Iterator[str]:
    """
    Yield an ordered sequence of location strings to try geocoding,
    starting with `location` itself, unmodified.

    Only yields fallback candidates when `location` contains no comma
    and has two or more whitespace-separated tokens - the exact shape
    a caller (or an upstream model) produces when it supplies a
    compound "city region [country]" string without punctuation (e.g.
    "Patna Bihar", "New York NY", "Patna Bihar India"). Every fallback
    candidate is a punctuation-only rewrite of `location`: it never
    reorders, substitutes, or drops any word, so it can only ever
    resolve to the same city the caller named - never a different
    one.

    Already comma-punctuated input (e.g. "Patna, Bihar") and
    single-token input (e.g. "Bengaluru") yield only the original
    string, since there is nothing left to reinterpret.

    Yields (in order, for a comma-free, multi-token `location`):
        1. `location`, unmodified.
        2. `location` with a comma inserted before its last token
           (covers a trailing region/country word, e.g.
           "Patna Bihar" -> "Patna, Bihar").
        3. Only when `location` has three or more tokens: `location`
           with commas inserted before each of its last two tokens
           (covers a trailing "region country" pair, e.g.
           "Patna Bihar India" -> "Patna, Bihar, India").
    """

    yield location

    if "," in location:
        return

    tokens = location.split()

    if len(tokens) < 2:
        return

    yield f"{' '.join(tokens[:-1])}, {tokens[-1]}"

    if len(tokens) >= 3:
        yield f"{' '.join(tokens[:-2])}, {tokens[-2]}, {tokens[-1]}"
