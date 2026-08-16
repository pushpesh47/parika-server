"""
Unit tests for `parika.tools.shell.config`.
"""

from __future__ import annotations

from pathlib import Path

from parika.core.configuration.configuration import Configuration
from parika.tools.shell.config import load_shell_config


class TestLoadShellConfig:
    def test_none_configuration_is_disabled_by_default(self) -> None:
        config = load_shell_config(None)

        assert config.enabled is False
        assert config.default_workspace is None

    def test_disabled_by_default_even_with_configuration(self) -> None:
        configuration = Configuration()
        configuration._config = {}  # noqa: SLF001

        config = load_shell_config(configuration)

        assert config.enabled is False

    def test_shell_enabled_key_is_authoritative(self) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "shell": {"enabled": True},
            "security": {"allow_shell_commands": False},
        }

        config = load_shell_config(configuration)

        assert config.enabled is True

    def test_falls_back_to_legacy_allow_shell_commands_when_shell_absent(
        self,
    ) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "security": {"allow_shell_commands": True}
        }

        config = load_shell_config(configuration)

        assert config.enabled is True

    def test_timeouts_and_limits_are_read(self) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "shell": {
                "enabled": True,
                "default_timeout_seconds": 5.0,
                "max_timeout_seconds": 60.0,
                "max_background_processes": 3,
                "output_buffer_max_bytes": 1024,
                "kill_grace_period_seconds": 1.5,
                "allow_shell_string": True,
                "inherit_environment": False,
            }
        }

        config = load_shell_config(configuration)

        assert config.default_timeout_seconds == 5.0
        assert config.max_timeout_seconds == 60.0
        assert config.max_background_processes == 3
        assert config.output_buffer_max_bytes == 1024
        assert config.kill_grace_period_seconds == 1.5
        assert config.allow_shell_string is True
        assert config.inherit_environment is False

    def test_default_workspace_resolves_against_project_root(self) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "shell": {"enabled": True},
            "workspace": {"default_workspace": "data"},
        }

        config = load_shell_config(configuration)

        assert config.default_workspace == (
            configuration.get_project_root() / "data"
        )

    def test_default_workspace_absolute_path_is_preserved(
        self, tmp_path: Path
    ) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "shell": {"enabled": True},
            "workspace": {"default_workspace": str(tmp_path)},
        }

        config = load_shell_config(configuration)

        assert config.default_workspace == tmp_path

    def test_default_workspace_falls_back_to_data_when_unconfigured(
        self,
    ) -> None:
        configuration = Configuration()
        configuration._config = {"shell": {"enabled": True}}  # noqa: SLF001

        config = load_shell_config(configuration)

        assert config.default_workspace == (
            configuration.get_project_root() / "data"
        )

    def test_empty_default_workspace_disables_it(self) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "shell": {"enabled": True},
            "workspace": {"default_workspace": ""},
        }

        config = load_shell_config(configuration)

        assert config.default_workspace is None
