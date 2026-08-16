"""
PARIKA Coding Tool - Configuration

Reads the `[coding]` TOML section through the existing `Configuration`
Core component, following the same pattern as
`parika/tools/filesystem/config.py`/`parika/tools/shell/config.py`.
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping

from parika.core.configuration.configuration import Configuration

DEFAULT_ENABLED = True
DEFAULT_TREE_SITTER_ENABLED = True
DEFAULT_MAX_FILE_SIZE_BYTES = 2_000_000
DEFAULT_INDEX_DATABASE = "coding_index.sqlite3"


def tree_sitter_dependency_available() -> bool:
    """
    Whether the optional `tree-sitter`/`tree-sitter-language-pack`
    dependency group is installed.
    """

    return (
        importlib.util.find_spec("tree_sitter") is not None
        and importlib.util.find_spec("tree_sitter_language_pack") is not None
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CodingToolConfig:
    """
    Immutable, typed snapshot of `[coding]` configuration.
    """

    enabled: bool = DEFAULT_ENABLED
    tree_sitter_enabled: bool = DEFAULT_TREE_SITTER_ENABLED
    max_file_size_bytes: int = DEFAULT_MAX_FILE_SIZE_BYTES
    index_database: str = DEFAULT_INDEX_DATABASE
    formatters: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )
    linters: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )


def load_coding_config(configuration: Configuration | None) -> CodingToolConfig:
    """
    Build a `CodingToolConfig` snapshot from `Configuration`.
    """

    if configuration is None:
        return CodingToolConfig(
            tree_sitter_enabled=(
                DEFAULT_TREE_SITTER_ENABLED and tree_sitter_dependency_available()
            )
        )

    tree_sitter_enabled = bool(
        configuration.get("coding.tree_sitter_enabled", DEFAULT_TREE_SITTER_ENABLED)
    ) and tree_sitter_dependency_available()

    raw_formatters = configuration.get("coding.formatters", {}) or {}
    raw_linters = configuration.get("coding.linters", {}) or {}

    return CodingToolConfig(
        enabled=bool(configuration.get("coding.enabled", DEFAULT_ENABLED)),
        tree_sitter_enabled=tree_sitter_enabled,
        max_file_size_bytes=int(
            configuration.get(
                "coding.max_file_size_bytes", DEFAULT_MAX_FILE_SIZE_BYTES
            )
        ),
        index_database=str(
            configuration.get("coding.index_database", DEFAULT_INDEX_DATABASE)
        ),
        formatters=MappingProxyType(
            {
                str(language): tuple(command)
                for language, command in dict(raw_formatters).items()
            }
        ),
        linters=MappingProxyType(
            {
                str(language): tuple(command)
                for language, command in dict(raw_linters).items()
            }
        ),
    )
