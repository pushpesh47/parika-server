"""
Unit tests for Configuration.

`Configuration` locates the real project root and, once `load()` is
called, reads the real `config/*.toml` files shipped with the
repository. These tests rely only on keys that are guaranteed to exist
in `config/defaults.toml` (see docs/Running.md) and never assert
values that could plausibly be overridden by optional layers.
"""

from __future__ import annotations

from pathlib import Path

from parika.core.configuration.configuration import Configuration


class TestUnloadedBehavior:
    def test_get_returns_default_before_load(self) -> None:
        configuration = Configuration()

        assert configuration.get("logging.level") is None
        assert configuration.get("logging.level", "fallback") == "fallback"

    def test_has_returns_false_before_load(self) -> None:
        configuration = Configuration()

        assert configuration.has("logging.level") is False

    def test_all_returns_empty_dict_before_load(self) -> None:
        configuration = Configuration()

        assert configuration.all() == {}


class TestProjectRoot:
    def test_project_root_contains_pyproject_toml(self) -> None:
        configuration = Configuration()

        root = configuration.get_project_root()

        assert isinstance(root, Path)
        assert (root / "pyproject.toml").exists()


class TestLoad:
    def test_load_populates_values_from_defaults(self) -> None:
        configuration = Configuration()
        configuration.load()

        # `application.name` and `logging.directory` are not
        # overridden by any of the optional higher-precedence layers
        # (installation/workspace/environment/runtime), unlike
        # `logging.level`, so they are safe to assert unconditionally.
        assert configuration.get("application.name") == "PARIKA"
        assert configuration.get("logging.directory") == "logs"

    def test_load_is_idempotent(self) -> None:
        configuration = Configuration()
        configuration.load()
        configuration.load()

        assert configuration.get("application.name") == "PARIKA"

    def test_has_returns_true_after_load(self) -> None:
        configuration = Configuration()
        configuration.load()

        assert configuration.has("logging.level") is True

    def test_has_returns_false_for_missing_key(self) -> None:
        configuration = Configuration()
        configuration.load()

        assert configuration.has("this.key.does.not.exist") is False


class TestGet:
    def test_get_supports_dot_notation(self) -> None:
        configuration = Configuration()
        configuration.load()

        assert configuration.get("logging.directory") == "logs"

    def test_get_returns_default_for_partially_missing_path(self) -> None:
        configuration = Configuration()
        configuration.load()

        assert (
            configuration.get("logging.level.nonexistent", "fallback")
            == "fallback"
        )

    def test_get_returns_default_for_completely_missing_top_level_key(
        self,
    ) -> None:
        configuration = Configuration()
        configuration.load()

        assert configuration.get("totally.unknown.key", "fallback") == (
            "fallback"
        )

    def test_get_returns_a_deep_copy(self) -> None:
        configuration = Configuration()
        configuration.load()

        application_section = configuration.get("application")
        assert isinstance(application_section, dict)

        application_section["name"] = "MUTATED"

        assert configuration.get("application.name") == "PARIKA"


class TestAll:
    def test_all_returns_full_merged_configuration(self) -> None:
        configuration = Configuration()
        configuration.load()

        everything = configuration.all()

        assert everything["application"]["name"] == "PARIKA"

    def test_all_returns_a_deep_copy(self) -> None:
        configuration = Configuration()
        configuration.load()

        everything = configuration.all()
        everything["application"]["name"] = "MUTATED"

        assert configuration.get("application.name") == "PARIKA"
