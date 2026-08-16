"""
Tests for `parika/server/config.py`'s `ServerSettings`/`load_server_settings()`,
focused on `[api].host` -- the LAN API binding requirement (see
`docs/guides/Running.md` section 12.2).

`[api].host` is read verbatim from the existing, layered `Configuration`
component (never a parallel config system, never hardcoded to
`"0.0.0.0"` anywhere in Python) and passed straight to `uvicorn.run()`
by `parika/server/__main__.py`. These tests only cover the
configuration-loading contract; live LAN listening behavior is verified
separately (see the task's live-verification report, not a unit test).
"""

from __future__ import annotations

from parika.server.config import ServerSettings, load_server_settings


class _FakeConfiguration:
    """
    Minimal Configuration stand-in exposing only `.get()`, matching the
    convention already used by `tests/server/test_cors.py`.
    """

    def __init__(self, values: dict) -> None:
        self._values = values

    def get(self, key, default=None):
        return self._values.get(key, default)


class TestServerSettingsHostDefaults:
    def test_default_host_is_loopback_only(self) -> None:
        settings = ServerSettings()

        assert settings.host == "127.0.0.1"

    def test_default_port_is_2026(self) -> None:
        settings = ServerSettings()

        assert settings.port == 2026


class TestLoadServerSettingsHost:
    def test_missing_host_falls_back_to_loopback_only(self) -> None:
        configuration = _FakeConfiguration({})

        settings = load_server_settings(configuration)  # type: ignore[arg-type]

        assert settings.host == "127.0.0.1"

    def test_explicit_loopback_host_is_loaded_unchanged(self) -> None:
        configuration = _FakeConfiguration({"api.host": "127.0.0.1"})

        settings = load_server_settings(configuration)  # type: ignore[arg-type]

        assert settings.host == "127.0.0.1"

    def test_explicit_lan_host_is_loaded_correctly(self) -> None:
        """
        `[api].host = "0.0.0.0"` (LAN-wide binding) must load exactly
        as configured -- this is an explicit operator choice, never a
        default, and never rewritten/validated away by this loader.
        """

        configuration = _FakeConfiguration({"api.host": "0.0.0.0"})

        settings = load_server_settings(configuration)  # type: ignore[arg-type]

        assert settings.host == "0.0.0.0"

    def test_explicit_other_bind_address_is_loaded_correctly(self) -> None:
        """
        Any explicitly configured bind address (e.g. a specific LAN
        interface IP) must load verbatim, not just "127.0.0.1"/"0.0.0.0".
        """

        configuration = _FakeConfiguration({"api.host": "192.168.1.100"})

        settings = load_server_settings(configuration)  # type: ignore[arg-type]

        assert settings.host == "192.168.1.100"

    def test_port_is_independent_of_host(self) -> None:
        configuration = _FakeConfiguration({"api.host": "0.0.0.0", "api.port": 2026})

        settings = load_server_settings(configuration)  # type: ignore[arg-type]

        assert settings.host == "0.0.0.0"
        assert settings.port == 2026
