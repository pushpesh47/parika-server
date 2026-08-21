"""
PARIKA Configuration Component

Responsible for loading, merging, validating, and providing
read-only access to the application's configuration.

This component acts as the single source of truth for all
configuration values used throughout PARIKA.
"""

from __future__ import annotations

import os
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

        # Load .env file if it exists
        self._load_dotenv()

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

        # Override with environment variables (highest precedence)
        self._apply_env_overrides()

        self._is_loaded = True

    def _load_dotenv(self) -> None:
        """Load environment variables from .env file if it exists."""
        env_path = self._project_root / ".env"
        if env_path.exists():
            with env_path.open("r") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, value = line.split("=", 1)
                        # Only set if not already in environment (environment takes precedence)
                        if key not in os.environ:
                            os.environ[key] = value

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides to configuration.

        Environment variables with PARIKA_ prefix are mapped to configuration keys.
        Format: PARIKA_SECTION__SUBSECTION__KEY = value (double underscore for nesting)
        Maps to: section.subsection.key
        """
        prefix = "PARIKA_"
        for env_key, env_value in os.environ.items():
            if env_key.startswith(prefix):
                # Convert PARIKA_DATABASE__HOST -> database.host
                # Use double underscore for nesting, single underscore stays as underscore
                config_key = env_key[len(prefix):].replace("__", ".").lower()
                self._set_nested_key(self._config, config_key, self._parse_env_value(env_value))

    def _parse_env_value(self, value: str) -> Any:
        """Parse environment variable value to appropriate type."""
        # Try to parse as boolean
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        # Try to parse as integer
        try:
            return int(value)
        except ValueError:
            pass
        # Try to parse as float
        try:
            return float(value)
        except ValueError:
            pass
        # Return as string
        return value

    def _set_nested_key(self, config: dict[str, Any], key: str, value: Any) -> None:
        """Set a nested configuration key using dot notation."""
        parts = key.split(".")
        current = config
        for part in parts[:-1]:
            if part not in current:
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

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