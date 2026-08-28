"""
Unit tests for PythonAstAnalyzer.
"""

from __future__ import annotations
from tests.conftest_db import build_test_db_config

from pathlib import Path

from parika.tools.coding.analyzers.python_ast import PythonAstAnalyzer
from parika.tools.coding.model import SymbolKind

SOURCE = '''"""Module docstring."""

import os
from collections import OrderedDict as OD


class Greeter:
    """Greets people."""

    def greet(self, name):
        """Greet someone."""
        return format_name(name)


def format_name(name):
    # TODO: support unicode normalization
    return name.strip()


TOP_LEVEL_VALUE = 1
'''


def test_supports_python_files_only() -> None:
    analyzer = PythonAstAnalyzer()

    assert analyzer.supports(Path("module.py"))
    assert not analyzer.supports(Path("module.js"))


def test_parse_extracts_module_class_method_function_and_variable() -> None:
    analyzer = PythonAstAnalyzer()
    parsed = analyzer.parse(Path("greeter.py"), SOURCE)

    names = {symbol.qualified_name: symbol for symbol in parsed.symbols}

    assert "greeter.greeter" not in names  # module symbol keeps file stem, not lowered
    assert "greeter.Greeter" in names
    assert names["greeter.Greeter"].kind is SymbolKind.CLASS

    assert "greeter.Greeter.greet" in names
    assert names["greeter.Greeter.greet"].kind is SymbolKind.METHOD

    assert "greeter.format_name" in names
    assert names["greeter.format_name"].kind is SymbolKind.FUNCTION

    assert "greeter.TOP_LEVEL_VALUE" in names
    assert names["greeter.TOP_LEVEL_VALUE"].kind is SymbolKind.VARIABLE

    module_symbols = [s for s in parsed.symbols if s.kind is SymbolKind.MODULE]
    assert module_symbols and module_symbols[0].docstring == "Module docstring."


def test_parse_extracts_imports() -> None:
    analyzer = PythonAstAnalyzer()
    parsed = analyzer.parse(Path("greeter.py"), SOURCE)

    modules = {edge.imported_module for edge in parsed.imports}
    assert "os" in modules
    assert "collections" in modules


def test_parse_extracts_call_edges() -> None:
    analyzer = PythonAstAnalyzer()
    parsed = analyzer.parse(Path("greeter.py"), SOURCE)

    callers = {edge.caller_qualified_name for edge in parsed.call_edges}
    assert "greeter.Greeter.greet" in callers

    callees = {
        edge.callee_qualified_name
        for edge in parsed.call_edges
        if edge.caller_qualified_name == "greeter.Greeter.greet"
    }
    assert "format_name" in callees


def test_parse_extracts_todo_annotation() -> None:
    analyzer = PythonAstAnalyzer()
    parsed = analyzer.parse(Path("greeter.py"), SOURCE)

    todo_texts = [a.text for a in parsed.annotations if a.kind.value == "todo"]
    assert any("unicode normalization" in text for text in todo_texts)


def test_parse_reports_syntax_error_as_diagnostic_not_exception() -> None:
    analyzer = PythonAstAnalyzer()
    parsed = analyzer.parse(Path("broken.py"), "def broken(:\n    pass\n")

    assert parsed.symbols == ()
    assert len(parsed.diagnostics) == 1
    assert parsed.diagnostics[0].severity == "error"
