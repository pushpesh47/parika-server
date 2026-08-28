"""
Unit tests for GenericTextAnalyzer and TreeSitterAnalyzer's graceful
degradation when the optional dependency group is not installed.
"""

from __future__ import annotations
from tests.conftest_db import build_test_db_config

from pathlib import Path

from parika.tools.coding.analyzers.generic_text import GenericTextAnalyzer
from parika.tools.coding.analyzers.registry import (
    DEFAULT_TREE_SITTER_LANGUAGE_IDS,
    LanguageAnalyzerRegistry,
    default_analyzers,
)
from parika.tools.coding.analyzers.tree_sitter_analyzer import TreeSitterAnalyzer
from parika.tools.coding.exceptions import LanguageAnalyzerUnavailableError


def test_generic_text_analyzer_supports_everything() -> None:
    analyzer = GenericTextAnalyzer()

    assert analyzer.supports(Path("script.sh"))
    assert analyzer.supports(Path("unknown.extension"))


def test_generic_text_analyzer_extracts_todo_comments() -> None:
    analyzer = GenericTextAnalyzer()
    parsed = analyzer.parse(
        Path("script.sh"), "#!/bin/bash\n# TODO: add error handling\necho hi\n"
    )

    assert len(parsed.annotations) == 1
    assert "add error handling" in parsed.annotations[0].text


def test_tree_sitter_analyzer_reports_unavailable_without_dependency() -> None:
    analyzer = TreeSitterAnalyzer("javascript")

    # The optional dependency group is not installed in this
    # environment, so the analyzer must degrade gracefully.
    assert analyzer.available is False
    assert analyzer.supports(Path("app.js")) is False


def test_tree_sitter_analyzer_parse_raises_when_forced_without_dependency() -> None:
    analyzer = TreeSitterAnalyzer("javascript")

    try:
        analyzer.parse(Path("app.js"), "function foo() {}")
        assert False, "expected LanguageAnalyzerUnavailableError"
    except LanguageAnalyzerUnavailableError:
        pass


def test_registry_falls_back_to_generic_text_for_unavailable_tree_sitter_language() -> None:
    registry = LanguageAnalyzerRegistry()
    analyzer = registry.resolve(Path("app.js"))

    assert isinstance(analyzer, GenericTextAnalyzer)


def test_registry_resolves_python_to_python_ast_analyzer() -> None:
    from parika.tools.coding.analyzers.python_ast import PythonAstAnalyzer

    registry = LanguageAnalyzerRegistry()
    analyzer = registry.resolve(Path("module.py"))

    assert isinstance(analyzer, PythonAstAnalyzer)


def test_default_analyzers_cover_every_tree_sitter_language_id() -> None:
    analyzers = default_analyzers()
    covered = {
        language_id
        for analyzer in analyzers
        for language_id in analyzer.language_ids()
    }

    for language_id in DEFAULT_TREE_SITTER_LANGUAGE_IDS:
        assert language_id in covered


def test_tree_sitter_disabled_by_config_is_not_registered() -> None:
    analyzers = default_analyzers(tree_sitter_enabled=False)
    assert not any(isinstance(a, TreeSitterAnalyzer) for a in analyzers)
