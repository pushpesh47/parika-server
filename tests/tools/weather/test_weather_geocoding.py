"""
Unit tests for `parika.tools.weather.geocoding`.
"""

from __future__ import annotations
from tests.conftest_db import build_test_db_config

import json
from urllib.parse import parse_qs, urlparse

import pytest

from parika.tools.weather.exceptions import LocationNotFoundError, WeatherNetworkError
from parika.tools.weather.geocoding import geocode, reverse_geocode
from parika.tools.weather.transport import HttpResponse

_EMPTY_RESULTS_BODY = json.dumps({"results": []}).encode()


def _found_body(name: str, *, country: str = "India") -> bytes:
    return json.dumps(
        {
            "results": [
                {
                    "name": name,
                    "latitude": 25.59,
                    "longitude": 85.13,
                    "country": country,
                    "timezone": "Asia/Kolkata",
                }
            ]
        }
    ).encode()


def _queried_name(url: str) -> str:
    """
    Extract and URL-decode the `name` query parameter from a
    geocoding request URL, for asserting exactly what was sent to
    Open-Meteo.
    """

    return parse_qs(urlparse(url).query)["name"][0]


class _FakeTransport:
    def __init__(self, body: bytes, status_code: int = 200) -> None:
        self.body = body
        self.status_code = status_code
        self.calls: list[str] = []

    def get(self, url: str, *, timeout: float) -> HttpResponse:
        self.calls.append(url)
        return HttpResponse(
            status_code=self.status_code, url=url, headers={}, body=self.body
        )


class _ScriptedTransport:
    """
    A transport whose response depends on the exact `name` query
    parameter of each request, so multi-candidate lookups can be
    exercised deterministically. Any query not present in `bodies`
    resolves to an empty-results response.
    """

    def __init__(self, bodies: dict[str, bytes]) -> None:
        self._bodies = bodies
        self.queried_names: list[str] = []

    def get(self, url: str, *, timeout: float) -> HttpResponse:
        name = _queried_name(url)
        self.queried_names.append(name)

        return HttpResponse(
            status_code=200,
            url=url,
            headers={},
            body=self._bodies.get(name, _EMPTY_RESULTS_BODY),
        )


class TestGeocode:
    def test_returns_best_match(self) -> None:
        body = json.dumps(
            {
                "results": [
                    {
                        "name": "Bengaluru",
                        "latitude": 12.97,
                        "longitude": 77.59,
                        "country": "India",
                        "timezone": "Asia/Kolkata",
                    }
                ]
            }
        ).encode()
        transport = _FakeTransport(body)

        result = geocode("Bengaluru", transport=transport, timeout_seconds=5.0)

        assert result.name == "Bengaluru"
        assert result.latitude == 12.97
        assert result.country == "India"
        # A single-token location that resolves on the first request
        # must never generate or issue a fallback candidate.
        assert len(transport.calls) == 1
        assert _queried_name(transport.calls[0]) == "Bengaluru"

    def test_raises_when_no_results(self) -> None:
        body = json.dumps({"results": []}).encode()
        transport = _FakeTransport(body)

        with pytest.raises(LocationNotFoundError):
            geocode("Nowhereville", transport=transport, timeout_seconds=5.0)

        # Single-token input has no fallback candidates to try: only
        # the original query is ever sent.
        assert len(transport.calls) == 1
        assert _queried_name(transport.calls[0]) == "Nowhereville"

    def test_raises_on_http_error(self) -> None:
        transport = _FakeTransport(b"error", status_code=500)

        with pytest.raises(WeatherNetworkError):
            geocode("Bengaluru", transport=transport, timeout_seconds=5.0)

    def test_raises_on_malformed_json(self) -> None:
        transport = _FakeTransport(b"not json")

        with pytest.raises(WeatherNetworkError):
            geocode("Bengaluru", transport=transport, timeout_seconds=5.0)


class TestGeocodeFallbackCandidates:
    """
    Covers the deterministic, comma-inserted fallback candidates
    generated when the caller's exact `location` string returns no
    results (e.g. "Patna Bihar" -> "Patna, Bihar").
    """

    def test_already_punctuated_location_uses_only_original_query(self) -> None:
        # "Patna, Bihar" already contains a comma, so no fallback
        # candidate is ever generated for it, even though it is
        # multi-token - it resolves on the very first request.
        transport = _ScriptedTransport({"Patna, Bihar": _found_body("Patna")})

        result = geocode("Patna, Bihar", transport=transport, timeout_seconds=5.0)

        assert result.name == "Patna"
        assert transport.queried_names == ["Patna, Bihar"]

    def test_multi_token_location_resolving_on_first_query_stays_single_call(
        self,
    ) -> None:
        # "New York City" happens to resolve as-is (a recognized
        # alias) - the fallback path must never be reached when the
        # very first query already returns a result.
        transport = _ScriptedTransport({"New York City": _found_body("New York")})

        result = geocode("New York City", transport=transport, timeout_seconds=5.0)

        assert result.name == "New York"
        assert transport.queried_names == ["New York City"]

    def test_falls_back_to_comma_before_last_token(self) -> None:
        # "Patna Bihar" fails as-is; the second candidate inserts a
        # comma before the last token and succeeds.
        transport = _ScriptedTransport({"Patna, Bihar": _found_body("Patna")})

        result = geocode("Patna Bihar", transport=transport, timeout_seconds=5.0)

        assert result.name == "Patna"
        assert transport.queried_names == ["Patna Bihar", "Patna, Bihar"]

    def test_falls_back_for_new_york_ny(self) -> None:
        transport = _ScriptedTransport({"New York, NY": _found_body("New York")})

        result = geocode("New York NY", transport=transport, timeout_seconds=5.0)

        assert result.name == "New York"
        assert transport.queried_names == ["New York NY", "New York, NY"]

    def test_falls_back_to_comma_before_last_two_tokens(self) -> None:
        # "Patna Bihar India" fails as-is; the second candidate
        # ("Patna Bihar, India") also fails; the third candidate
        # splits both trailing tokens and succeeds.
        transport = _ScriptedTransport(
            {"Patna, Bihar, India": _found_body("Patna")}
        )

        result = geocode(
            "Patna Bihar India", transport=transport, timeout_seconds=5.0
        )

        assert result.name == "Patna"
        assert transport.queried_names == [
            "Patna Bihar India",
            "Patna Bihar, India",
            "Patna, Bihar, India",
        ]

    def test_two_token_exhaustion_raises_with_original_location(self) -> None:
        # No candidate resolves: exactly the 2 candidates a two-token,
        # comma-free string can produce are tried, then
        # LocationNotFoundError is raised quoting the *original*
        # string, not a rewritten candidate.
        transport = _ScriptedTransport({})

        with pytest.raises(LocationNotFoundError, match=r"'Patna Xyzzy'"):
            geocode("Patna Xyzzy", transport=transport, timeout_seconds=5.0)

        assert transport.queried_names == ["Patna Xyzzy", "Patna, Xyzzy"]

    def test_three_token_exhaustion_tries_every_candidate_then_raises(self) -> None:
        transport = _ScriptedTransport({})

        with pytest.raises(LocationNotFoundError, match=r"'Foo Bar Baz'"):
            geocode("Foo Bar Baz", transport=transport, timeout_seconds=5.0)

        assert transport.queried_names == [
            "Foo Bar Baz",
            "Foo Bar, Baz",
            "Foo, Bar, Baz",
        ]

    def test_http_error_on_first_candidate_short_circuits_without_fallback(
        self,
    ) -> None:
        # A transport/provider error is not an empty match - it must
        # propagate immediately and must never trigger a fallback
        # candidate.
        transport = _FakeTransport(b"error", status_code=500)

        with pytest.raises(WeatherNetworkError):
            geocode("Patna Bihar", transport=transport, timeout_seconds=5.0)

        assert len(transport.calls) == 1

    def test_malformed_json_on_first_candidate_short_circuits_without_fallback(
        self,
    ) -> None:
        transport = _FakeTransport(b"not json")

        with pytest.raises(WeatherNetworkError):
            geocode("Patna Bihar", transport=transport, timeout_seconds=5.0)

        assert len(transport.calls) == 1


class TestReverseGeocodeNominatim:
    """
    Tests for Nominatim reverse geocoding with structured address parsing.
    """

    def test_suburb_city_state_country(self) -> None:
        """suburb=Matwari, city=Hazaribagh, state=Jharkhand, country=India -> 'Matwari, Hazaribagh, Jharkhand, India'."""
        nominatim_body = json.dumps(
            {
                "place_id": 12345678,
                "licence": "Data © OpenStreetMap contributors, ODbL 1.0.",
                "osm_type": "way",
                "osm_id": 12345678,
                "boundingbox": ["24.00", "24.02"],
                "lat": "24.0091136",
                "lon": "85.3803008",
                "display_name": "Matwari, Hazaribagh, Jharkhand, 825300, India",
                "address": {
                    "suburb": "Matwari",
                    "city": "Hazaribagh",
                    "state": "Jharkhand",
                    "country": "India",
                    "postcode": "825300",
                },
            }
        ).encode()
        transport = _FakeTransport(nominatim_body)

        result = reverse_geocode(
            latitude=24.0091136,
            longitude=85.3803008,
            transport=transport,
            timeout_seconds=5.0,
        )

        assert result == "Matwari, Hazaribagh, Jharkhand, India"

    def test_postcode_excluded(self) -> None:
        """Postcode should not be included in the location name."""
        nominatim_body = json.dumps(
            {
                "place_id": 12345678,
                "licence": "Data © OpenStreetMap contributors, ODbL 1.0.",
                "osm_type": "way",
                "osm_id": 12345678,
                "boundingbox": ["24.00", "24.02"],
                "lat": "24.0091136",
                "lon": "85.3803008",
                "display_name": "Matwari, Hazaribagh, Jharkhand, 825300, India",
                "address": {
                    "suburb": "Matwari",
                    "city": "Hazaribagh",
                    "state": "Jharkhand",
                    "country": "India",
                    "postcode": "825300",
                },
            }
        ).encode()
        transport = _FakeTransport(nominatim_body)

        result = reverse_geocode(
            latitude=24.0091136,
            longitude=85.3803008,
            transport=transport,
            timeout_seconds=5.0,
        )

        assert result == "Matwari, Hazaribagh, Jharkhand, India"
        # Verify postcode '825300' is NOT in the result
        assert "825300" not in result

    def test_missing_suburb_falls_back_to_city(self) -> None:
        """When suburb is missing, fall back to city."""
        nominatim_body = json.dumps(
            {
                "place_id": 12345678,
                "licence": "Data © OpenStreetMap contributors, ODbL 1.0.",
                "osm_type": "way",
                "osm_id": 12345678,
                "boundingbox": ["24.00", "24.02"],
                "lat": "24.0091136",
                "lon": "85.3803008",
                "display_name": "Hazaribagh, Jharkhand, India",
                "address": {
                    "city": "Hazaribagh",
                    "state": "Jharkhand",
                    "country": "India",
                },
            }
        ).encode()
        transport = _FakeTransport(nominatim_body)

        result = reverse_geocode(
            latitude=24.0091136,
            longitude=85.3803008,
            transport=transport,
            timeout_seconds=5.0,
        )

        assert result == "Hazaribagh, Jharkhand, India"

    def test_missing_locality_falls_back_to_coordinates(self) -> None:
        """When no locality fields are available, fall back to coordinate string."""
        nominatim_body = json.dumps(
            {
                "place_id": 12345678,
                "licence": "Data © OpenStreetMap contributors, ODbL 1.0.",
                "osm_type": "way",
                "osm_id": 12345678,
                "boundingbox": ["24.00", "24.02"],
                "lat": "24.0091136",
                "lon": "85.3803008",
                "display_name": "Some unknown location",
                "address": {
                    "state": "Jharkhand",
                    "country": "India",
                },
            }
        ).encode()
        transport = _FakeTransport(nominatim_body)

        result = reverse_geocode(
            latitude=24.0091136,
            longitude=85.3803008,
            transport=transport,
            timeout_seconds=5.0,
        )

        # Fallback should use city/state + country when state is present
        assert result == "Jharkhand, India"

    def test_no_address_components_falls_back_to_coordinates(self) -> None:
        """When no address components are available, use coordinate fallback."""
        nominatim_body = json.dumps(
            {
                "place_id": 12345678,
                "licence": "Data © OpenStreetMap contributors, ODbL 1.0.",
                "osm_type": "way",
                "osm_id": 12345678,
                "boundingbox": ["24.00", "24.02"],
                "lat": "24.0091136",
                "lon": "85.3803008",
                "display_name": "Unknown",
                "address": {},
            }
        ).encode()
        transport = _FakeTransport(nominatim_body)

        result = reverse_geocode(
            latitude=24.0091136,
            longitude=85.3803008,
            transport=transport,
            timeout_seconds=5.0,
        )

        # Should fall back to coordinate format
        assert result == "24.0091, 85.3803"

    def test_neighbourhood_preferred_over_city(self) -> None:
        """neighbourhood should be preferred over city when both are present."""
        nominatim_body = json.dumps(
            {
                "place_id": 12345678,
                "licence": "Data © OpenStreetMap contributors, ODbL 1.0.",
                "osm_type": "way",
                "osm_id": 12345678,
                "boundingbox": ["24.00", "24.02"],
                "lat": "24.0091136",
                "lon": "85.3803008",
                "display_name": "Neighbourhood, City, State, Country",
                "address": {
                    "neighbourhood": "Neighbourhood",
                    "city": "City",
                    "state": "State",
                    "country": "Country",
                },
            }
        ).encode()
        transport = _FakeTransport(nominatim_body)

        result = reverse_geocode(
            latitude=24.0091136,
            longitude=85.3803008,
            transport=transport,
            timeout_seconds=5.0,
        )

        # neighbourhood should be preferred over city
        assert result == "Neighbourhood, State, Country"

    def test_missing_state_country_only(self) -> None:
        """When only country is present, return just country."""
        nominatim_body = json.dumps(
            {
                "place_id": 12345678,
                "licence": "Data © OpenStreetMap contributors, ODbL 1.0.",
                "osm_type": "way",
                "osm_id": 12345678,
                "boundingbox": ["24.00", "24.02"],
                "lat": "24.0091136",
                "lon": "85.3803008",
                "display_name": "Country",
                "address": {
                    "country": "India",
                },
            }
        ).encode()
        transport = _FakeTransport(nominatim_body)

        result = reverse_geocode(
            latitude=24.0091136,
            longitude=85.3803008,
            transport=transport,
            timeout_seconds=5.0,
        )

        assert result == "India"

    def test_missing_locality_all_fields_absent(self) -> None:
        """When all locality fields are absent but state and country exist."""
        nominatim_body = json.dumps(
            {
                "place_id": 12345678,
                "licence": "Data © OpenStreetMap contributors, ODbL 1.0.",
                "osm_type": "way",
                "osm_id": 12345678,
                "boundingbox": ["24.00", "24.02"],
                "lat": "24.0091136",
                "lon": "85.3803008",
                "display_name": "State, Country",
                "address": {
                    "state": "Jharkhand",
                    "country": "India",
                },
            }
        ).encode()
        transport = _FakeTransport(nominatim_body)

        result = reverse_geocode(
            latitude=24.0091136,
            longitude=85.3803008,
            transport=transport,
            timeout_seconds=5.0,
        )

        assert result == "Jharkhand, India"

    def test_no_address_returns_none(self) -> None:
        """When Nominatim returns no address, return None."""
        nominatim_body = json.dumps({}).encode()
        transport = _FakeTransport(nominatim_body)

        result = reverse_geocode(
            latitude=24.0091136,
            longitude=85.3803008,
            transport=transport,
            timeout_seconds=5.0,
        )

        assert result is None
