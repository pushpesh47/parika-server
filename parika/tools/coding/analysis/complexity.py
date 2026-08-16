"""
PARIKA Coding Tool - Complexity Analysis

Stdlib-only cyclomatic-complexity-style metric per function/method,
counting AST branch nodes (McCabe, 1976). Implemented for Python via
the `ast` module; other languages report `None` (not computed) rather
than a misleading value, matching the analyzer registry's own
graceful-degradation posture.
"""

from __future__ import annotations

import ast

from parika.tools.coding.model import ComplexityResult

_BRANCH_NODE_TYPES: tuple[type, ...] = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.ExceptHandler,
    ast.With,
    ast.AsyncWith,
    ast.BoolOp,
    ast.IfExp,
)


def compute_python_complexity(
    text: str, file_path: str
) -> tuple[ComplexityResult, ...]:
    """
    Compute one `ComplexityResult` per top-level function and per
    method, for a Python source file.
    """

    try:
        tree = ast.parse(text, filename=file_path)
    except SyntaxError:
        return ()

    module_name = file_path.rsplit("/", 1)[-1].removesuffix(".py")
    results: list[ComplexityResult] = []

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    results.append(
                        _complexity_for(
                            child, f"{module_name}.{node.name}.{child.name}", file_path
                        )
                    )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            results.append(
                _complexity_for(node, f"{module_name}.{node.name}", file_path)
            )

    return tuple(results)


def _complexity_for(
    node: "ast.FunctionDef | ast.AsyncFunctionDef",
    qualified_name: str,
    file_path: str,
) -> ComplexityResult:
    complexity = 1

    for child in ast.walk(node):
        if isinstance(child, _BRANCH_NODE_TYPES):
            complexity += 1

    return ComplexityResult(
        symbol_qualified_name=qualified_name,
        file_path=file_path,
        complexity=complexity,
        line_start=node.lineno,
        line_end=getattr(node, "end_lineno", node.lineno) or node.lineno,
    )
