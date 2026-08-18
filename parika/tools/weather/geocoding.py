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

from parika.core.logger.logger import Logger
from .exceptions import LocationNotFoundError, WeatherNetworkError, WeatherTimeoutError
from .transport import HttpTransport

GEOCODING_ENDPOINT = "https://geocoding-api.open-meteo.com/v1/search"
NOMINATIM_REVERSE_ENDPOINT = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_USER_AGENT = "PARIKA/1.0 (https://github.com/parika-org/parika)"


def reverse_geocode(
    latitude: float,
    longitude: float,
    *,
    transport: HttpTransport,
    timeout_seconds: float,
    logger: Logger | None = None,
) -> str | None:
    """
    Resolve coordinates to a human-readable location name using
    Nominatim's reverse geocoding with structured address parsing.

    Args:
        latitude: Latitude in decimal degrees.
        longitude: Longitude in decimal degrees.
        transport: HttpTransport used to issue the request.
        timeout_seconds: Maximum time, in seconds, to wait for the request.
        logger: Optional logger for diagnostic output. When provided,
            failures are logged at WARNING level.

    Returns:
        Resolved location name (e.g. "Matwari, Hazaribagh, Jharkhand, India"),
        or None if reverse geocoding fails or returns no results.
    """
    # Nominatim reverse geocoding endpoint with required parameters
    url = f"{NOMINATIM_REVERSE_ENDPOINT}?lat={latitude}&lon={longitude}&format=json&addressdetails=1&accept-language=en"

    log = logger if logger else None

    try:
        response = transport.get(url, timeout=timeout_seconds)

        if response.status_code >= 400:
            if log:
                log.warning(
                    "Reverse geocoding failed: provider=Nominatim "
                    f"status={response.status_code} latitude={latitude} "
                    f"longitude={longitude}"
                )
            return None

        payload = json.loads(response.body.decode("utf-8", errors="replace"))
        address = payload.get("address") or {}

        # Build location name from structured address.
        # Include locality fields in priority order (suburb > neighbourhood > village > town > city > municipality),
        # then append state and country. Avoid duplicates.
        locality_fields = (
            "suburb",
            "neighbourhood",
            "village",
            "town",
            "city",
            "municipality",
        )

        # Build location name from structured address.
        # Priority: suburb > neighbourhood > village > town > city > municipality
        # Rules:
        # - If suburb is present: include suburb + city + state + country
        # - If neighbourhood is present (no suburb): include neighbourhood only (exclude city)
        # - If only city is present (no suburb, no neighbourhood): include city + state + country
        # - If no locality fields: fall back to state/country or coordinate fallback
        suburb = address.get("suburb")
        neighbourhood = address.get("neighbourhood")
        village = address.get("village")
        town = address.get("town")
        city = address.get("city")
        municipality = address.get("municipality")

        parts = []

        if suburb:
            # Suburb is most precise: include suburb + city + state + country
            parts.append(suburb)
            city_val = address.get("city")
            if city_val and city_val != suburb:
                parts.append(city_val)
        elif neighbourhood:
            # Neighbourhood takes priority over city: include only neighbourhood
            parts.append(neighbourhood)
        elif village:
            parts.append(village)
        elif town:
            parts.append(town)
        elif city:
            # Only city (no suburb/neighbourhood/village/town): include city + state + country
            parts.append(city)
        elif municipality:
            parts.append(municipality)
        # else: no locality fields - will fall back to state/country or coordinates

        # Append state if present
        state = address.get("state")
        if state:
            parts.append(state)

        # Append country if present
        country = address.get("country")
        if country:
            parts.append(country)

        # If no parts were generated (no locality fields, no state, no country),
        # fall back to coordinate string format - unless Nominatim returned
        # no address at all (no 'address' key in payload), in which case return None.
        if not parts:
            if "address" not in payload:
                # Nominatim returned no address data at all
                if log:
                    log.debug(
                        "Reverse geocoding: provider=Nominatim returned no address data "
                        f"latitude={latitude} longitude={longitude}"
                    )
                return None
            # Fall back to coordinate string format
            fallback = f"{latitude:.4f}, {longitude:.4f}"
            return fallback

        resolved = ", ".join(parts)
        if log:
            log.debug(
                "Reverse geocoding succeeded: provider=Nominatim "
                f"latitude={latitude} longitude={longitude} name={resolved}"
            )
        return resolved

    except WeatherTimeoutError as ex:
        if log:
            log.warning(
                "Reverse geocoding timeout: provider=Nominatim "
                f"latitude={latitude} longitude={longitude} "
                f"timeout_seconds={timeout_seconds} error={ex}"
            )
        return None

    except WeatherNetworkError as ex:
        if log:
            log.warning(
                "Reverse geocoding network error: provider=Nominatim "
                f"latitude={latitude} longitude={longitude} error={ex}"
            )
        return None

    except json.JSONDecodeError as ex:
        if log:
            log.warning(
                "Reverse geocoding malformed response: provider=Nominatim "
                f"latitude={latitude} longitude={longitude} error={ex}"
            )
        return None

    except Exception as ex:
        if log:
            log.warning(
                "Reverse geocoding unexpected error: provider=Nominatim "
                f"latitude={latitude} longitude={longitude} "
                f"exception={type(ex).__name__} error={ex}"
            )
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
