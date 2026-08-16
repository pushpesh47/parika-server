"""
Tests for PARIKA Server's CORS configuration and its wiring into
`CORSMiddleware`.

Covers three layers:

  - `ApiCorsSettings`'s own defaults (`parika/server/config.py`).
  - `load_server_settings()` reading `[api.cors]` through the existing
    `Configuration` component (never a parallel config system),
    mirroring the `_FakeConfiguration` convention already used by
    `tests/core/planner/model_selection/test_config.py` and
    `tests/providers/local_speech/test_config.py`.
  - The actual `CORSMiddleware` request/response behavior that
    `parika/server/app.py`'s `create_app()` wires up, verified both
    against a minimal middleware-only app (deterministic, no
    `ParikaRuntime`) and against the real `create_app()` (so the
    real `config/defaults.toml` on disk is exercised end-to-end).

The web client is an independent static bundle that may be served
from an arbitrary `http://localhost:<port>`/`http://127.0.0.1:<port>`
development port (see `web/index.html`'s own header comment) -
`allow_origin_regex` exists specifically to allow that without ever
allowing external hosts, LAN IPs, or other domains.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from parika.server.app import create_app
from parika.server.config import ApiCorsSettings, load_server_settings


class _FakeConfiguration:
    """
    Minimal Configuration stand-in exposing only `.get()`, used to
    verify override-merging behavior deterministically without
    depending on real TOML files on disk.
    """

    def __init__(self, values: dict) -> None:
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


class TestApiCorsSettingsDefaults:
    def test_default_allow_origin_regex_permits_loopback_dev_ports(self) -> None:
        settings = ApiCorsSettings()

        assert (
            settings.allow_origin_regex
            == r"http://(127\.0\.0\.1|localhost)(?::\d+)?"
        )

    def test_default_allow_origins_is_empty(self) -> None:
        settings = ApiCorsSettings()

        assert settings.allow_origins == ()


class TestLoadServerSettingsCors:
    def test_reads_allow_origin_regex_from_configuration(self) -> None:
        configuration = _FakeConfiguration(
            {"api.cors.allow_origin_regex": r"http://localhost:\d+"}
        )

        settings = load_server_settings(configuration)  # type: ignore[arg-type]

        assert settings.cors.allow_origin_regex == r"http://localhost:\d+"

    def test_missing_allow_origin_regex_falls_back_to_the_built_in_default(
        self,
    ) -> None:
        configuration = _FakeConfiguration({})

        settings = load_server_settings(configuration)  # type: ignore[arg-type]

        assert (
            settings.cors.allow_origin_regex
            == r"http://(127\.0\.0\.1|localhost)(?::\d+)?"
        )

    def test_allow_origin_regex_can_be_explicitly_disabled(self) -> None:
        configuration = _FakeConfiguration(
            {"api.cors.allow_origin_regex": None}
        )

        settings = load_server_settings(configuration)  # type: ignore[arg-type]

        assert settings.cors.allow_origin_regex is None

    def test_exact_allow_origins_support_is_unchanged(self) -> None:
        configuration = _FakeConfiguration(
            {
                "api.cors.allow_origins": ["https://app.example.com"],
                "api.cors.allow_origin_regex": None,
            }
        )

        settings = load_server_settings(configuration)  # type: ignore[arg-type]

        assert settings.cors.allow_origins == ("https://app.example.com",)

    def test_default_allow_lan_origin_regex_is_disabled(self) -> None:
        configuration = _FakeConfiguration({})

        settings = load_server_settings(configuration)  # type: ignore[arg-type]

        assert settings.cors.allow_lan_origin_regex is None

    def test_empty_string_allow_lan_origin_regex_is_normalized_to_disabled(
        self,
    ) -> None:
        """
        `config/defaults.toml` stores the disabled state as `""` (TOML
        has no native `None`) -- this must be treated identically to
        never having been configured at all.
        """

        configuration = _FakeConfiguration({"api.cors.allow_lan_origin_regex": ""})

        settings = load_server_settings(configuration)  # type: ignore[arg-type]

        assert settings.cors.allow_lan_origin_regex is None

    def test_explicit_allow_lan_origin_regex_is_loaded(self) -> None:
        configuration = _FakeConfiguration(
            {
                "api.cors.allow_lan_origin_regex": r"http://192\.168\.1\.100(?::\d+)?"
            }
        )

        settings = load_server_settings(configuration)  # type: ignore[arg-type]

        assert (
            settings.cors.allow_lan_origin_regex
            == r"http://192\.168\.1\.100(?::\d+)?"
        )


class TestEffectiveAllowOriginRegex:
    def test_with_no_lan_regex_configured_equals_the_localhost_regex_alone(
        self,
    ) -> None:
        settings = ApiCorsSettings()

        assert (
            settings.effective_allow_origin_regex == settings.allow_origin_regex
        )

    def test_with_both_regexes_disabled_is_none(self) -> None:
        settings = ApiCorsSettings(allow_origin_regex=None)

        assert settings.effective_allow_origin_regex is None

    def test_combines_localhost_and_lan_regexes(self) -> None:
        settings = ApiCorsSettings(
            allow_lan_origin_regex=r"http://192\.168\.1\.100(?::\d+)?"
        )

        combined = settings.effective_allow_origin_regex

        assert combined is not None
        assert settings.allow_origin_regex is not None
        assert f"(?:{settings.allow_origin_regex})" in combined
        assert "(?:http://192\\.168\\.1\\.100(?::\\d+)?)" in combined


def _build_cors_only_app(cors_settings: ApiCorsSettings) -> FastAPI:
    """
    A minimal app wired the same way `create_app()` wires
    `CORSMiddleware` (`parika/server/app.py`), without constructing a
    full `ParikaRuntime` - keeps the origin-matching tests fast and
    deterministic.
    """

    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_settings.allow_origins),
        allow_origin_regex=cors_settings.effective_allow_origin_regex,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/probe")
    def probe() -> dict:
        return {"status": "ok"}

    return app


class TestCorsMiddlewareOriginMatching:
    def test_localhost_with_arbitrary_port_preflight_is_allowed(self) -> None:
        app = _build_cors_only_app(ApiCorsSettings())

        with TestClient(app) as client:
            response = client.options(
                "/probe",
                headers={
                    "Origin": "http://localhost:5500",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 200
        assert (
            response.headers["access-control-allow-origin"]
            == "http://localhost:5500"
        )

    def test_127_0_0_1_with_arbitrary_port_preflight_is_allowed(self) -> None:
        app = _build_cors_only_app(ApiCorsSettings())

        with TestClient(app) as client:
            response = client.options(
                "/probe",
                headers={
                    "Origin": "http://127.0.0.1:8080",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 200
        assert (
            response.headers["access-control-allow-origin"]
            == "http://127.0.0.1:8080"
        )

    def test_localhost_without_a_port_preflight_is_allowed(self) -> None:
        """
        Apache (and other reverse proxies/static servers) serving the
        Web Client on the default HTTP port (80) produce an `Origin`
        header with no `:<port>` suffix at all, e.g.
        `http://localhost/parika-web/` -> `Origin: http://localhost`.
        """

        app = _build_cors_only_app(ApiCorsSettings())

        with TestClient(app) as client:
            response = client.options(
                "/probe",
                headers={
                    "Origin": "http://localhost",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost"

    def test_127_0_0_1_without_a_port_preflight_is_allowed(self) -> None:
        app = _build_cors_only_app(ApiCorsSettings())

        with TestClient(app) as client:
            response = client.options(
                "/probe",
                headers={
                    "Origin": "http://127.0.0.1",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://127.0.0.1"

    def test_https_localhost_is_not_allowed(self) -> None:
        """
        `allow_origin_regex` intentionally allows only `http://`, per
        the requirement to never allow HTTPS.
        """

        app = _build_cors_only_app(ApiCorsSettings())

        with TestClient(app) as client:
            response = client.options(
                "/probe",
                headers={
                    "Origin": "https://localhost",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers

    def test_unrelated_external_origin_preflight_is_rejected(self) -> None:
        app = _build_cors_only_app(ApiCorsSettings())

        with TestClient(app) as client:
            response = client.options(
                "/probe",
                headers={
                    "Origin": "https://example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers

    def test_lan_ip_is_not_allowed_by_default(self) -> None:
        """
        With `allow_lan_origin_regex` unset (the default), a LAN
        origin must be rejected exactly like any other external
        origin -- LAN exposure requires an explicit opt-in.
        """

        app = _build_cors_only_app(ApiCorsSettings())

        with TestClient(app) as client:
            response = client.options(
                "/probe",
                headers={
                    "Origin": "http://192.168.1.10:5500",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers

    def test_lookalike_localhost_subdomain_is_not_allowed(self) -> None:
        app = _build_cors_only_app(ApiCorsSettings())

        with TestClient(app) as client:
            response = client.options(
                "/probe",
                headers={
                    "Origin": "http://localhost.example.com:5500",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers

    def test_neighboring_loopback_address_is_not_allowed(self) -> None:
        app = _build_cors_only_app(ApiCorsSettings())

        with TestClient(app) as client:
            response = client.options(
                "/probe",
                headers={
                    "Origin": "http://127.0.0.2:5500",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers

    def test_actual_get_response_carries_the_allow_origin_header_too(
        self,
    ) -> None:
        app = _build_cors_only_app(ApiCorsSettings())

        with TestClient(app) as client:
            response = client.get(
                "/probe", headers={"Origin": "http://localhost:5500"}
            )

        assert response.status_code == 200
        assert (
            response.headers["access-control-allow-origin"]
            == "http://localhost:5500"
        )

    def test_exact_allow_origins_entry_still_works_alongside_the_regex(
        self,
    ) -> None:
        app = _build_cors_only_app(
            ApiCorsSettings(
                allow_origins=("https://app.example.com",),
                allow_origin_regex=r"http://(127\.0\.0\.1|localhost)(?::\d+)?",
            )
        )

        with TestClient(app) as client:
            response = client.options(
                "/probe",
                headers={
                    "Origin": "https://app.example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 200
        assert (
            response.headers["access-control-allow-origin"]
            == "https://app.example.com"
        )


class TestCreateAppCorsWiring:
    """
    End-to-end checks against the real `create_app()`, which reads
    `[api.cors]` from the real `config/defaults.toml` on disk (see
    `_peek_cors_settings()` in `parika/server/app.py`) - these confirm
    the fix actually took effect for the deployed configuration, not
    just for hand-built `ApiCorsSettings` instances.
    """

    def test_localhost_preflight_succeeds_against_the_real_app(
        self, runtime_factory
    ) -> None:
        app = create_app(runtime_factory=runtime_factory)

        with TestClient(app) as client:
            response = client.options(
                "/api/v1/health",
                headers={
                    "Origin": "http://localhost:5500",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 200
        assert (
            response.headers["access-control-allow-origin"]
            == "http://localhost:5500"
        )

    def test_127_0_0_1_preflight_succeeds_against_the_real_app(
        self, runtime_factory
    ) -> None:
        app = create_app(runtime_factory=runtime_factory)

        with TestClient(app) as client:
            response = client.options(
                "/api/v1/health",
                headers={
                    "Origin": "http://127.0.0.1:5500",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 200
        assert (
            response.headers["access-control-allow-origin"]
            == "http://127.0.0.1:5500"
        )

    def test_localhost_without_a_port_preflight_succeeds_against_the_real_app(
        self, runtime_factory
    ) -> None:
        """
        Reproduces the live-tested Apache case: the Web Client served
        at `http://localhost/parika-web/` sends `Origin: http://localhost`
        (no `:80`).
        """

        app = create_app(runtime_factory=runtime_factory)

        with TestClient(app) as client:
            response = client.options(
                "/api/v1/status",
                headers={
                    "Origin": "http://localhost",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 200
        assert response.headers["access-control-allow-origin"] == "http://localhost"

    def test_external_origin_preflight_is_rejected_against_the_real_app(
        self, runtime_factory
    ) -> None:
        app = create_app(runtime_factory=runtime_factory)

        with TestClient(app) as client:
            response = client.options(
                "/api/v1/health",
                headers={
                    "Origin": "https://example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers


class TestLanOriginCorsWhenExplicitlyConfigured:
    """
    Covers the LAN Web Client CORS requirement:
    `allow_lan_origin_regex`, when an operator explicitly configures
    it (e.g. in `config/installation.toml`), must allow that LAN
    origin while continuing to allow localhost/127.0.0.1 and continuing
    to reject unrelated external origins -- never `allow_origins =
    ["*"]`, never a broad subnet wildcard.
    """

    _LAN_REGEX = r"http://192\.168\.1\.100(?::\d+)?"

    def test_configured_lan_origin_preflight_is_allowed(self) -> None:
        app = _build_cors_only_app(
            ApiCorsSettings(allow_lan_origin_regex=self._LAN_REGEX)
        )

        with TestClient(app) as client:
            response = client.options(
                "/probe",
                headers={
                    "Origin": "http://192.168.1.100",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 200
        assert (
            response.headers["access-control-allow-origin"]
            == "http://192.168.1.100"
        )

    def test_configured_lan_origin_with_port_preflight_is_allowed(self) -> None:
        app = _build_cors_only_app(
            ApiCorsSettings(allow_lan_origin_regex=self._LAN_REGEX)
        )

        with TestClient(app) as client:
            response = client.options(
                "/probe",
                headers={
                    "Origin": "http://192.168.1.100:8080",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 200
        assert (
            response.headers["access-control-allow-origin"]
            == "http://192.168.1.100:8080"
        )

    def test_localhost_still_allowed_alongside_a_configured_lan_regex(
        self,
    ) -> None:
        """
        Enabling a LAN origin must not disturb existing
        localhost/127.0.0.1 CORS behavior.
        """

        app = _build_cors_only_app(
            ApiCorsSettings(allow_lan_origin_regex=self._LAN_REGEX)
        )

        with TestClient(app) as client:
            response = client.options(
                "/probe",
                headers={
                    "Origin": "http://localhost:5500",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 200
        assert (
            response.headers["access-control-allow-origin"]
            == "http://localhost:5500"
        )

    def test_a_different_lan_ip_than_configured_is_still_rejected(self) -> None:
        """
        The configured LAN regex must match only the explicitly
        configured address, never every private IP address.
        """

        app = _build_cors_only_app(
            ApiCorsSettings(allow_lan_origin_regex=self._LAN_REGEX)
        )

        with TestClient(app) as client:
            response = client.options(
                "/probe",
                headers={
                    "Origin": "http://192.168.1.101:5500",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers

    def test_unrelated_external_origin_still_rejected_alongside_lan_regex(
        self,
    ) -> None:
        app = _build_cors_only_app(
            ApiCorsSettings(allow_lan_origin_regex=self._LAN_REGEX)
        )

        with TestClient(app) as client:
            response = client.options(
                "/probe",
                headers={
                    "Origin": "https://example.com",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers

    def test_https_lan_origin_is_still_rejected(self) -> None:
        """
        The configured pattern is `http://` only, mirroring the
        existing localhost regex's own `http`-only scheme -- HTTPS
        origins are never implicitly allowed.
        """

        app = _build_cors_only_app(
            ApiCorsSettings(allow_lan_origin_regex=self._LAN_REGEX)
        )

        with TestClient(app) as client:
            response = client.options(
                "/probe",
                headers={
                    "Origin": "https://192.168.1.100",
                    "Access-Control-Request-Method": "GET",
                },
            )

        assert response.status_code == 400
        assert "access-control-allow-origin" not in response.headers

    def test_no_wildcard_origin_is_ever_introduced(self) -> None:
        """
        Defense-in-depth: even with a LAN regex configured,
        `allow_origins` must never contain the literal wildcard
        `"*"` -- CORS must remain allow-list/regex-driven only.
        """

        settings = ApiCorsSettings(allow_lan_origin_regex=self._LAN_REGEX)

        assert "*" not in settings.allow_origins
