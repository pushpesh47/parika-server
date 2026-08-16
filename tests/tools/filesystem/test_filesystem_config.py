"""
Unit tests for `parika.tools.filesystem.config`.
"""

from __future__ import annotations

from pathlib import Path

from parika.core.configuration.configuration import Configuration
from parika.tools.filesystem.config import load_filesystem_config


class TestLoadFilesystemConfig:
    def test_none_configuration_denies_by_default(self) -> None:
        config = load_filesystem_config(None)

        assert config.allowed_roots == ()
        assert config.enabled is True

    def test_relative_roots_resolve_against_project_root(self) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "filesystem": {"allowed_roots": ["data"]}
        }

        config = load_filesystem_config(configuration)

        assert config.allowed_roots == (
            configuration.get_project_root() / "data",
        )

    def test_absolute_roots_are_preserved(self, tmp_path: Path) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "filesystem": {"allowed_roots": [str(tmp_path)]},
            # Disabling the auto-trusted default workspace isolates
            # this test to its own concern: that an absolute
            # `allowed_roots`/`trusted_workspaces` entry is preserved
            # as-is rather than being (incorrectly) re-anchored to the
            # project root. `default_workspace`'s own auto-inclusion
            # is covered by TestDefaultWorkspace below.
            "workspace": {"default_workspace": ""},
        }

        config = load_filesystem_config(configuration)

        assert config.allowed_roots == (tmp_path,)

    def test_trusted_workspaces_key_is_preferred_over_legacy_allowed_roots(
        self, tmp_path: Path
    ) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "filesystem": {
                "trusted_workspaces": [str(tmp_path)],
                "allowed_roots": ["/should/not/be/used"],
            },
            "workspace": {"default_workspace": ""},
        }

        config = load_filesystem_config(configuration)

        assert config.allowed_roots == (tmp_path,)


class TestDefaultWorkspace:
    def test_default_workspace_is_included_automatically(
        self, tmp_path: Path
    ) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "filesystem": {"trusted_workspaces": [str(tmp_path)]},
            "workspace": {"default_workspace": "some_workspace"},
        }

        config = load_filesystem_config(configuration)

        assert tmp_path in config.allowed_roots
        assert (
            configuration.get_project_root() / "some_workspace"
        ) in config.allowed_roots

    def test_default_workspace_falls_back_to_data_when_unconfigured(
        self,
    ) -> None:
        configuration = Configuration()
        configuration._config = {"filesystem": {"trusted_workspaces": []}}  # noqa: SLF001

        config = load_filesystem_config(configuration)

        assert (
            configuration.get_project_root() / "data"
        ) in config.allowed_roots

    def test_empty_default_workspace_disables_auto_inclusion(self) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "filesystem": {"trusted_workspaces": []},
            "workspace": {"default_workspace": ""},
        }

        config = load_filesystem_config(configuration)

        assert config.allowed_roots == ()

    def test_default_workspace_is_not_duplicated_if_already_listed(
        self, tmp_path: Path
    ) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "filesystem": {"trusted_workspaces": [str(tmp_path)]},
            "workspace": {"default_workspace": str(tmp_path)},
        }

        config = load_filesystem_config(configuration)

        assert config.allowed_roots == (tmp_path,)


class TestOtherFlags:
    def test_allow_write_and_allow_delete_are_read(self) -> None:
        configuration = Configuration()
        configuration._config = {  # noqa: SLF001
            "filesystem": {"allow_write": False, "allow_delete": True}
        }

        config = load_filesystem_config(configuration)

        assert config.allow_write is False
        assert config.allow_delete is True

    def test_disabled_flag_is_read(self) -> None:
        configuration = Configuration()
        configuration._config = {"filesystem": {"enabled": False}}  # noqa: SLF001

        config = load_filesystem_config(configuration)

        assert config.enabled is False
