"""
PARIKA Server - Configuration

Small helper that reads the `[api]`/`[api.auth]`/`[api.cors]`/
`[api.rate_limit]` configuration sections (see
`docs/guides/Running.md` section 12.5/12.6) through the existing,
unmodified `Configuration` component. Contains no business logic of
its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from parika.core.configuration.configuration import Configuration


@dataclass(frozen=True, slots=True, kw_only=True)
class ApiAuthSettings:
    mode: str = "none"
    api_keys: tuple[str, ...] = ()
    jwt_secret: str = ""
    jwt_expiry_seconds: int = 3600


@dataclass(frozen=True, slots=True, kw_only=True)
class ApiCorsSettings:
    allow_origins: tuple[str, ...] = ()
    allow_origin_regex: str | None = r"http://(127\.0\.0\.1|localhost)(?::\d+)?"
    # Additional, explicitly configured origin pattern for a LAN Web
    # Client (e.g. Apache serving it at `http://192.168.1.100/...`,
    # which sends `Origin: http://192.168.1.100`). Empty/`None` (the
    # default) disables LAN origin matching entirely -- LAN exposure
    # is always an explicit configuration choice, never a silent
    # default change. When set, it is combined with (never replaces)
    # `allow_origin_regex` above -- see `effective_allow_origin_regex`.
    allow_lan_origin_regex: str | None = None

    @property
    def effective_allow_origin_regex(self) -> str | None:
        """
        The single regex actually handed to `CORSMiddleware`
        (`parika/server/app.py`), combining the always-on
        `allow_origin_regex` (localhost/127.0.0.1 by default) with the
        optional `allow_lan_origin_regex`, if any operator has
        explicitly configured one. Returns `None` when neither pattern
        is configured, exactly like `CORSMiddleware`'s own "no regex
        matching" behavior.
        """

        patterns = [
            pattern
            for pattern in (self.allow_origin_regex, self.allow_lan_origin_regex)
            if pattern
        ]

        if not patterns:
            return None

        if len(patterns) == 1:
            return patterns[0]

        return "|".join(f"(?:{pattern})" for pattern in patterns)


@dataclass(frozen=True, slots=True, kw_only=True)
class ApiRateLimitSettings:
    enabled: bool = False
    requests_per_minute: int = 120


@dataclass(frozen=True, slots=True, kw_only=True)
class ServerSettings:
    enabled: bool = True
    host: str = "127.0.0.1"
    port: int = 2026
    auth: ApiAuthSettings = field(default_factory=ApiAuthSettings)
    cors: ApiCorsSettings = field(default_factory=ApiCorsSettings)
    rate_limit: ApiRateLimitSettings = field(default_factory=ApiRateLimitSettings)


def load_server_settings(configuration: Configuration) -> ServerSettings:
    """
    Read the Server Runtime's own settings from `configuration`
    (already loaded/merged through the existing layered
    Configuration component -- never a parallel config system).
    """

    return ServerSettings(
        enabled=bool(configuration.get("api.enabled", True)),
        host=str(configuration.get("api.host", "127.0.0.1")),
        port=int(configuration.get("api.port", 2026)),
        auth=ApiAuthSettings(
            mode=str(configuration.get("api.auth.mode", "none")),
            api_keys=tuple(configuration.get("api.auth.api_keys", [])),
            jwt_secret=str(configuration.get("api.auth.jwt_secret", "")),
            jwt_expiry_seconds=int(
                configuration.get("api.auth.jwt_expiry_seconds", 3600)
            ),
        ),
        cors=ApiCorsSettings(
            allow_origins=tuple(
                configuration.get("api.cors.allow_origins", [])
            ),
            allow_origin_regex=configuration.get(
                "api.cors.allow_origin_regex",
                r"http://(127\.0\.0\.1|localhost)(?::\d+)?",
            ),
            allow_lan_origin_regex=configuration.get(
                "api.cors.allow_lan_origin_regex", None
            ) or None,
        ),
        rate_limit=ApiRateLimitSettings(
            enabled=bool(configuration.get("api.rate_limit.enabled", False)),
            requests_per_minute=int(
                configuration.get("api.rate_limit.requests_per_minute", 120)
            ),
        ),
    )
