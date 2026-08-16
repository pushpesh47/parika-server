"""
PARIKA Coding Tool - Tree-sitter Analyzer

Optional, multi-language `LanguageAnalyzer` backed by the `tree-sitter`
+ `tree-sitter-language-pack` optional dependency group
(`[project.optional-dependencies].coding`). Gracefully unavailable
(never crashing) when that extra is not installed -- see
docs/development/Tool_Guide.md sections
4.4 and 14.

Extraction is intentionally best-effort and structural (function/class/
import declarations only, via a small per-language node-type mapping),
not a full semantic analysis -- see section 4.4's comparison against
full Language Server implementations for the rationale.
"""

from __future__ import annotations

import hashlib
import importlib.util
from collections.abc import Mapping
from pathlib import Path

from parika.tools.coding.exceptions import LanguageAnalyzerUnavailableError
from parika.tools.coding.model import (
    ImportEdge,
    ParsedFile,
    Symbol,
    SymbolKind,
)

from .base import ConfigurableCommandsMixin

#: Per-language declaration node type names, best-effort and
#: intentionally small -- extending coverage for a language never
#: requires touching any other language's entry.
_FUNCTION_NODE_TYPES: Mapping[str, tuple[str, ...]] = {
    "javascript": ("function_declaration", "method_definition"),
    "typescript": ("function_declaration", "method_definition"),
    "java": ("method_declaration",),
    "kotlin": ("function_declaration",),
    "go": ("function_declaration", "method_declaration"),
    "rust": ("function_item",),
    "c": ("function_definition",),
    "cpp": ("function_definition",),
    "c_sharp": ("method_declaration",),
    "php": ("function_definition", "method_declaration"),
    "bash": ("function_definition",),
}

_CLASS_NODE_TYPES: Mapping[str, tuple[str, ...]] = {
    "javascript": ("class_declaration",),
    "typescript": ("class_declaration",),
    "java": ("class_declaration",),
    "kotlin": ("class_declaration",),
    "go": ("type_declaration",),
    "rust": ("struct_item", "impl_item"),
    "cpp": ("class_specifier",),
    "c_sharp": ("class_declaration",),
    "php": ("class_declaration",),
}

_IMPORT_NODE_TYPES: Mapping[str, tuple[str, ...]] = {
    "javascript": ("import_statement",),
    "typescript": ("import_statement",),
    "java": ("import_declaration",),
    "go": ("import_spec",),
    "rust": ("use_declaration",),
    "c": ("preproc_include",),
    "cpp": ("preproc_include",),
    "php": ("namespace_use_declaration",),
}

_EXTENSION_TO_LANGUAGE: Mapping[str, str] = {
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".java": "java",
    ".kt": "kotlin",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".cs": "c_sharp",
    ".php": "php",
    ".html": "html",
    ".css": "css",
    ".sql": "sql",
    ".sh": "bash",
    ".bash": "bash",
    ".ps1": "powershell",
}


def _dependency_available() -> bool:
    return (
        importlib.util.find_spec("tree_sitter") is not None
        and importlib.util.find_spec("tree_sitter_language_pack") is not None
    )


class TreeSitterAnalyzer(ConfigurableCommandsMixin):
    """
    `LanguageAnalyzer` implementation backed by Tree-sitter, covering
    every required language beyond Python.

    Constructed once per language id by `LanguageAnalyzerRegistry`.
    `supports()` returns `False` whenever the optional dependency group
    is not installed, so the registry transparently falls back to
    `GenericTextAnalyzer` for that file -- exactly the "not crashing,
    not registered at all" degradation this design documents.
    """

    def __init__(
        self,
        language_id: str,
        *,
        formatters: Mapping[str, tuple[str, ...]] | None = None,
        linters: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        super().__init__(formatters=formatters, linters=linters)

        self._language_id = language_id
        self._available = _dependency_available()
        self._extensions = tuple(
            extension
            for extension, language in _EXTENSION_TO_LANGUAGE.items()
            if language == language_id
        )

    @property
    def available(self) -> bool:
        """
        Whether the optional Tree-sitter dependency group is
        installed.
        """

        return self._available

    def language_ids(self) -> tuple[str, ...]:
        return (self._language_id,)

    def supports(self, path: Path) -> bool:
        return self._available and path.suffix in self._extensions

    def parse(self, path: Path, text: str) -> ParsedFile:
        """
        Parse `text` using Tree-sitter.

        Raises:
            LanguageAnalyzerUnavailableError:
                If called directly (bypassing `supports()`) while the
                optional dependency group is not installed.
        """

        if not self._available:
            raise LanguageAnalyzerUnavailableError(
                f"Tree-sitter support for '{self._language_id}' "
                "requires the optional 'coding' dependency group "
                "(tree-sitter, tree-sitter-language-pack) to be "
                "installed."
            )

        # Imported lazily -- only reached when `_available` is True,
        # so this module never fails to import when the optional
        # extra is absent.
        from tree_sitter_language_pack import get_parser  # type: ignore[import-not-found]

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        parser = get_parser(self._language_id)
        tree = parser.parse(text.encode("utf-8"))

        module_name = path.stem
        symbols: list[Symbol] = []
        imports: list[ImportEdge] = []

        function_types = _FUNCTION_NODE_TYPES.get(self._language_id, ())
        class_types = _CLASS_NODE_TYPES.get(self._language_id, ())
        import_types = _IMPORT_NODE_TYPES.get(self._language_id, ())

        for node in _walk(tree.root_node):
            if node.type in function_types:
                name = _node_name(node, text)
                if name:
                    symbols.append(
                        Symbol(
                            id=f"{path}:{node.start_point[0] + 1}:function:{name}",
                            file_path=str(path),
                            kind=SymbolKind.FUNCTION,
                            name=name,
                            qualified_name=f"{module_name}.{name}",
                            line_start=node.start_point[0] + 1,
                            line_end=node.end_point[0] + 1,
                        )
                    )
            elif node.type in class_types:
                name = _node_name(node, text)
                if name:
                    symbols.append(
                        Symbol(
                            id=f"{path}:{node.start_point[0] + 1}:class:{name}",
                            file_path=str(path),
                            kind=SymbolKind.CLASS,
                            name=name,
                            qualified_name=f"{module_name}.{name}",
                            line_start=node.start_point[0] + 1,
                            line_end=node.end_point[0] + 1,
                        )
                    )
            elif node.type in import_types:
                imports.append(
                    ImportEdge(
                        file_path=str(path),
                        imported_module=_node_text(node, text).strip(),
                        line=node.start_point[0] + 1,
                    )
                )

        return ParsedFile(
            file_path=str(path),
            language=self._language_id,
            content_hash=content_hash,
            symbols=tuple(symbols),
            imports=tuple(imports),
        )


def _walk(node: object):
    stack = [node]

    while stack:
        current = stack.pop()
        yield current
        stack.extend(reversed(current.children))  # type: ignore[attr-defined]


def _node_text(node: object, text: str) -> str:
    return text.encode("utf-8")[node.start_byte : node.end_byte].decode(  # type: ignore[attr-defined]
        "utf-8", errors="replace"
    )


def _node_name(node: object, text: str) -> str | None:
    name_node = node.child_by_field_name("name")  # type: ignore[attr-defined]

    if name_node is None:
        return None

    return _node_text(name_node, text)
