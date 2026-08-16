"""
PARIKA Configuration Component

Responsible for loading, merging, validating, and providing
read-only access to the application's configuration.

This component acts as the single source of truth for all
configuration values used throughout PARIKA.
"""

from __future__ import annotations

import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any

from .merger import Merger


class Configuration:
    """
    Central configuration service.

    Configuration is composed of multiple layers that are merged into
    a single read-only configuration exposed to the rest of PARIKA.

    Layer precedence (lowest → highest):

        defaults
            ↓
        installation
            ↓
        workspace
            ↓
        environment
            ↓
        runtime
    """

    def __init__(self) -> None:
        """Initialize the configuration component."""

        self._project_root = self._find_project_root()
        self._config: dict[str, Any] = {}
        self._is_loaded = False

    def load(self) -> None:
        """
        Load and merge all configuration files.

        Required:
            config/defaults.toml

        Optional:
            config/installation.toml
            config/workspace.toml
            config/environment.toml
            config/runtime.toml
        """

        if self._is_loaded:
            return

        config_directory = self._project_root / "config"

        defaults = self._load_required(config_directory / "defaults.toml")
        installation = self._load_optional(config_directory / "installation.toml")
        workspace = self._load_optional(config_directory / "workspace.toml")
        environment = self._load_optional(config_directory / "environment.toml")
        runtime = self._load_optional(config_directory / "runtime.toml")

        merger = Merger()

        self._config = merger.merge_layers(
            defaults,
            installation,
            workspace,
            environment,
            runtime,
        )

        self._is_loaded = True

    def has(self, key: str) -> bool:
        """
        Determine whether a configuration key exists.
        """

        value: Any = self._config

        for part in key.split("."):

            if not isinstance(value, dict):
                return False

            if part not in value:
                return False

            value = value[part]

        return True

    def get(
        self,
        key: str,
        default: Any = None,
    ) -> Any:
        """
        Retrieve a configuration value using dot notation.

        Example
        -------

            database.host
            ai.default_model
        """

        value: Any = self._config

        for part in key.split("."):

            if not isinstance(value, dict):
                return deepcopy(default)

            if part not in value:
                return deepcopy(default)

            value = value[part]

        return deepcopy(value)

    def all(self) -> dict[str, Any]:
        """
        Return the complete merged configuration.
        """

        return deepcopy(self._config)

    def _find_project_root(self) -> Path:
        """
        Locate the PARIKA project root.

        The project root is identified by the presence of
        pyproject.toml.
        """

        current = Path(__file__).resolve().parent

        for directory in [current, *current.parents]:

            if (directory / "pyproject.toml").exists():
                return directory

        raise FileNotFoundError(
            "Unable to locate the PARIKA project root."
        )

    def _load_required(
        self,
        file_path: Path,
    ) -> dict[str, Any]:
        """
        Load a required TOML configuration file.
        """

        if not file_path.exists():
            raise FileNotFoundError(
                f"Required configuration file not found: {file_path}"
            )

        with file_path.open("rb") as stream:
            return tomllib.load(stream)

    def _load_optional(
        self,
        file_path: Path,
    ) -> dict[str, Any]:
        """
        Load an optional TOML configuration file.
        """

        if not file_path.exists():
            return {}

        with file_path.open("rb") as stream:
            return tomllib.load(stream)


    def get_project_root(self) -> Path:
        """
        Return the PARIKA project root directory.
        """

        return self._project_root