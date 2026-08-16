"""
PARIKA Coding Tool - Python AST Analyzer

Stdlib-only `LanguageAnalyzer` for Python, using the `ast` module.
Always available, zero new dependency -- the canonical implementation
every other analyzer's degradation path falls back toward for Python
specifically.

This supersedes and is shared with `CodeKnowledgeEngine`'s own, far
smaller symbol/import extraction (see
docs/development/Tool_Guide.md sections
4.4 and 7.4): `CodeKnowledgeEngine` delegates to this analyzer rather
than re-implementing its own `ast`-walking logic.
"""

from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

from parika.tools.coding.model import (
    Annotation,
    AnnotationKind,
    CallEdge,
    Diagnostic,
    ImportEdge,
    ParsedFile,
    ReferenceEdge,
    ReferenceKind,
    Symbol,
    SymbolKind,
)

from .base import ConfigurableCommandsMixin

_MARKER_PATTERN = re.compile(
    r"#\s*(TODO|FIXME|HACK|XXX)\b[:\s]*(.*)", re.IGNORECASE
)
_MARKER_KIND = {
    "TODO": AnnotationKind.TODO,
    "FIXME": AnnotationKind.FIXME,
    "HACK": AnnotationKind.FIXME,
    "XXX": AnnotationKind.FIXME,
}


class PythonAstAnalyzer(ConfigurableCommandsMixin):
    """
    `LanguageAnalyzer` implementation for Python, backed entirely by
    the standard library `ast` module.
    """

    def language_ids(self) -> tuple[str, ...]:
        return ("python",)

    def supports(self, path: Path) -> bool:
        return path.suffix == ".py"

    def parse(self, path: Path, text: str) -> ParsedFile:
        """
        Parse `text` into an immutable `ParsedFile`.

        A syntax error is reported as a `Diagnostic`, not raised --
        parsing a file with a syntax error should never abort an
        entire repository-wide indexing pass.
        """

        module_name = path.stem
        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()

        try:
            tree = ast.parse(text, filename=str(path))
        except SyntaxError as ex:
            return ParsedFile(
                file_path=str(path),
                language="python",
                content_hash=content_hash,
                diagnostics=(
                    Diagnostic(
                        message=str(ex.msg),
                        line=ex.lineno or 0,
                        column=(ex.offset or 1) - 1,
                        severity="error",
                    ),
                ),
            )

        symbols: list[Symbol] = []
        imports: list[ImportEdge] = []
        references: list[ReferenceEdge] = []
        call_edges: list[CallEdge] = []

        module_doc = ast.get_docstring(tree)
        if module_doc:
            symbols.append(
                Symbol(
                    id=f"{path}:0:module",
                    file_path=str(path),
                    kind=SymbolKind.MODULE,
                    name=module_name,
                    qualified_name=module_name,
                    docstring=module_doc,
                    line_start=1,
                    line_end=1,
                )
            )

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(
                        ImportEdge(
                            file_path=str(path),
                            imported_module=alias.name,
                            line=node.lineno,
                        )
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    imports.append(
                        ImportEdge(
                            file_path=str(path),
                            imported_module=module,
                            imported_symbol=alias.name,
                            line=node.lineno,
                        )
                    )

        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                class_qualified_name = f"{module_name}.{node.name}"
                symbols.append(_class_symbol(path, module_name, node))

                for child in node.body:
                    if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_qualified_name = f"{class_qualified_name}.{child.name}"
                        symbols.append(
                            _function_symbol(
                                path,
                                class_qualified_name,
                                child,
                                kind=SymbolKind.METHOD,
                            )
                        )
                        call_edges.extend(
                            _call_edges_for(method_qualified_name, child)
                        )
                        references.extend(_references_for(str(path), child))

            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                function_qualified_name = f"{module_name}.{node.name}"
                symbols.append(
                    _function_symbol(
                        path, module_name, node, kind=SymbolKind.FUNCTION
                    )
                )
                call_edges.extend(_call_edges_for(function_qualified_name, node))
                references.extend(_references_for(str(path), node))

            elif isinstance(node, ast.Assign):
                symbols.extend(
                    _variable_symbols(path, module_name, node)
                )

        annotations = _extract_annotations(path, text, tree)

        return ParsedFile(
            file_path=str(path),
            language="python",
            content_hash=content_hash,
            symbols=tuple(symbols),
            imports=tuple(imports),
            references=tuple(references),
            call_edges=tuple(call_edges),
            annotations=annotations,
        )


def _class_symbol(path: Path, module_name: str, node: ast.ClassDef) -> Symbol:
    bases = ", ".join(_unparse(base) for base in node.bases)
    signature = f"class {node.name}({bases})" if bases else f"class {node.name}"

    return Symbol(
        id=f"{path}:{node.lineno}:class:{node.name}",
        file_path=str(path),
        kind=SymbolKind.CLASS,
        name=node.name,
        qualified_name=f"{module_name}.{node.name}",
        signature=signature,
        docstring=ast.get_docstring(node),
        line_start=node.lineno,
        line_end=getattr(node, "end_lineno", node.lineno) or node.lineno,
    )


def _function_symbol(
    path: Path,
    scope_qualified_name: str,
    node: "ast.FunctionDef | ast.AsyncFunctionDef",
    *,
    kind: SymbolKind,
) -> Symbol:
    args = ", ".join(arg.arg for arg in node.args.args)
    prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
    signature = f"{prefix} {node.name}({args})"

    return Symbol(
        id=f"{path}:{node.lineno}:{kind.value}:{node.name}",
        file_path=str(path),
        kind=kind,
        name=node.name,
        qualified_name=f"{scope_qualified_name}.{node.name}",
        signature=signature,
        docstring=ast.get_docstring(node),
        line_start=node.lineno,
        line_end=getattr(node, "end_lineno", node.lineno) or node.lineno,
    )


def _variable_symbols(
    path: Path, module_name: str, node: ast.Assign
) -> list[Symbol]:
    symbols: list[Symbol] = []

    for target in node.targets:
        if isinstance(target, ast.Name):
            symbols.append(
                Symbol(
                    id=f"{path}:{node.lineno}:variable:{target.id}",
                    file_path=str(path),
                    kind=SymbolKind.VARIABLE,
                    name=target.id,
                    qualified_name=f"{module_name}.{target.id}",
                    line_start=node.lineno,
                    line_end=getattr(node, "end_lineno", node.lineno) or node.lineno,
                )
            )

    return symbols


def _call_edges_for(
    caller_qualified_name: str,
    node: "ast.FunctionDef | ast.AsyncFunctionDef",
) -> list[CallEdge]:
    edges: list[CallEdge] = []

    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            callee_name = _call_target_name(child.func)

            if callee_name:
                edges.append(
                    CallEdge(
                        caller_qualified_name=caller_qualified_name,
                        callee_qualified_name=callee_name,
                    )
                )

    return edges


def _references_for(
    file_path: str, node: "ast.FunctionDef | ast.AsyncFunctionDef"
) -> list[ReferenceEdge]:
    references: list[ReferenceEdge] = []

    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            kind = (
                ReferenceKind.WRITE
                if isinstance(child.ctx, (ast.Store, ast.Del))
                else ReferenceKind.READ
            )
            references.append(
                ReferenceEdge(
                    file_path=file_path,
                    symbol_qualified_name=child.id,
                    kind=kind,
                    line=getattr(child, "lineno", 0),
                    column=getattr(child, "col_offset", 0),
                )
            )
        elif isinstance(child, ast.Call):
            callee_name = _call_target_name(child.func)

            if callee_name:
                references.append(
                    ReferenceEdge(
                        file_path=file_path,
                        symbol_qualified_name=callee_name,
                        kind=ReferenceKind.CALL,
                        line=getattr(child, "lineno", 0),
                        column=getattr(child, "col_offset", 0),
                    )
                )

    return references


def _call_target_name(func_node: ast.expr) -> str | None:
    if isinstance(func_node, ast.Name):
        return func_node.id

    if isinstance(func_node, ast.Attribute):
        return func_node.attr

    return None


def _extract_annotations(
    path: Path, text: str, tree: ast.Module
) -> tuple[Annotation, ...]:
    annotations: list[Annotation] = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        match = _MARKER_PATTERN.search(line)

        if match:
            keyword = match.group(1).upper()
            annotations.append(
                Annotation(
                    file_path=str(path),
                    kind=_MARKER_KIND.get(keyword, AnnotationKind.COMMENT),
                    text=match.group(2).strip() or keyword,
                    line=line_number,
                )
            )

    module_doc = ast.get_docstring(tree)
    if module_doc:
        annotations.append(
            Annotation(
                file_path=str(path),
                kind=AnnotationKind.DOCSTRING,
                text=module_doc,
                line=1,
            )
        )

    return tuple(annotations)


def _unparse(node: ast.expr) -> str:
    try:
        return ast.unparse(node)
    except Exception:
        return "<expr>"
