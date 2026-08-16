"""
PARIKA Repository Intelligence - Project Detector

`ProjectDetector` Protocol + default implementations -- the fourth/
fifth instance of the "Protocol + registry + default implementations"
shape already used by `ScoringRule`, `KnowledgeEngine`,
and the Coding Tool's own `LanguageAnalyzer`. Satisfies Project
Awareness: automatic detection of framework, language, package
manager, build system, test framework, linter, and formatter (see
docs/development/Module_Guide.md section
7.2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol, runtime_checkable

from parika.modules.repository_intelligence.workspace.workspace_model import (
    ProjectSummary,
)


@runtime_checkable
class ProjectDetector(Protocol):
    """
    One implementation per ecosystem. Adding a new ecosystem is: write
    one new `ProjectDetector`, add one entry to
    `ProjectDetectorRegistry`'s default tuple -- zero changes anywhere
    else.
    """

    def ecosystem(self) -> str: ...

    def manifest_filenames(self) -> tuple[str, ...]:
        """Exact manifest filenames this detector recognizes."""
        ...

    def manifest_suffixes(self) -> tuple[str, ...]:
        """Manifest file suffixes this detector recognizes (e.g. `.csproj`)."""
        ...

    def describe(self, manifest_path: Path, text: str) -> ProjectSummary: ...


class _BaseDetector:
    def manifest_suffixes(self) -> tuple[str, ...]:
        return ()


class PythonProjectDetector(_BaseDetector):
    def ecosystem(self) -> str:
        return "python"

    def manifest_filenames(self) -> tuple[str, ...]:
        return ("pyproject.toml", "setup.py", "requirements.txt")

    def describe(self, manifest_path: Path, text: str) -> ProjectSummary:
        lowered = text.lower()

        return ProjectSummary(
            root=manifest_path.parent,
            ecosystem=self.ecosystem(),
            manifest_path=manifest_path,
            framework=_first_match(lowered, ("django", "fastapi", "flask")),
            package_manager="uv" if "uv" in lowered else "pip",
            build_system="setuptools" if "setuptools" in lowered else None,
            test_framework="pytest" if "pytest" in lowered else None,
            linter="ruff" if "ruff" in lowered else None,
            formatter="ruff" if "ruff" in lowered else "black" if "black" in lowered else None,
        )


class NodeProjectDetector(_BaseDetector):
    def ecosystem(self) -> str:
        return "node"

    def manifest_filenames(self) -> tuple[str, ...]:
        return ("package.json",)

    def describe(self, manifest_path: Path, text: str) -> ProjectSummary:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            data = {}

        dependencies = {
            **data.get("dependencies", {}),
            **data.get("devDependencies", {}),
        }

        return ProjectSummary(
            root=manifest_path.parent,
            ecosystem=self.ecosystem(),
            manifest_path=manifest_path,
            framework=_first_match_keys(dependencies, ("react", "vue", "express", "next")),
            package_manager="npm",
            test_framework=_first_match_keys(dependencies, ("jest", "mocha", "vitest")),
            linter="eslint" if "eslint" in dependencies else None,
            formatter="prettier" if "prettier" in dependencies else None,
        )


class GoProjectDetector(_BaseDetector):
    def ecosystem(self) -> str:
        return "go"

    def manifest_filenames(self) -> tuple[str, ...]:
        return ("go.mod",)

    def describe(self, manifest_path: Path, text: str) -> ProjectSummary:
        return ProjectSummary(
            root=manifest_path.parent,
            ecosystem=self.ecosystem(),
            manifest_path=manifest_path,
            package_manager="go modules",
            build_system="go build",
            test_framework="go test",
        )


class RustProjectDetector(_BaseDetector):
    def ecosystem(self) -> str:
        return "rust"

    def manifest_filenames(self) -> tuple[str, ...]:
        return ("Cargo.toml",)

    def describe(self, manifest_path: Path, text: str) -> ProjectSummary:
        return ProjectSummary(
            root=manifest_path.parent,
            ecosystem=self.ecosystem(),
            manifest_path=manifest_path,
            package_manager="cargo",
            build_system="cargo",
            test_framework="cargo test",
        )


class JavaProjectDetector(_BaseDetector):
    def ecosystem(self) -> str:
        return "java"

    def manifest_filenames(self) -> tuple[str, ...]:
        return ("pom.xml", "build.gradle", "build.gradle.kts")

    def describe(self, manifest_path: Path, text: str) -> ProjectSummary:
        build_system = "maven" if manifest_path.name == "pom.xml" else "gradle"

        return ProjectSummary(
            root=manifest_path.parent,
            ecosystem=self.ecosystem(),
            manifest_path=manifest_path,
            package_manager=build_system,
            build_system=build_system,
            test_framework="junit" if "junit" in text.lower() else None,
        )


class CSharpProjectDetector(_BaseDetector):
    def ecosystem(self) -> str:
        return "csharp"

    def manifest_filenames(self) -> tuple[str, ...]:
        return ()

    def manifest_suffixes(self) -> tuple[str, ...]:
        return (".csproj",)

    def describe(self, manifest_path: Path, text: str) -> ProjectSummary:
        return ProjectSummary(
            root=manifest_path.parent,
            ecosystem=self.ecosystem(),
            manifest_path=manifest_path,
            package_manager="nuget",
            build_system="dotnet",
        )


class PhpProjectDetector(_BaseDetector):
    def ecosystem(self) -> str:
        return "php"

    def manifest_filenames(self) -> tuple[str, ...]:
        return ("composer.json",)

    def describe(self, manifest_path: Path, text: str) -> ProjectSummary:
        lowered = text.lower()

        return ProjectSummary(
            root=manifest_path.parent,
            ecosystem=self.ecosystem(),
            manifest_path=manifest_path,
            framework=_first_match(lowered, ("laravel", "symfony")),
            package_manager="composer",
        )


class CppProjectDetector(_BaseDetector):
    def ecosystem(self) -> str:
        return "cpp"

    def manifest_filenames(self) -> tuple[str, ...]:
        return ("CMakeLists.txt", "Makefile")

    def describe(self, manifest_path: Path, text: str) -> ProjectSummary:
        build_system = "cmake" if manifest_path.name == "CMakeLists.txt" else "make"

        return ProjectSummary(
            root=manifest_path.parent,
            ecosystem=self.ecosystem(),
            manifest_path=manifest_path,
            build_system=build_system,
        )


def default_project_detectors() -> tuple[ProjectDetector, ...]:
    return (
        PythonProjectDetector(),
        NodeProjectDetector(),
        GoProjectDetector(),
        RustProjectDetector(),
        JavaProjectDetector(),
        CSharpProjectDetector(),
        PhpProjectDetector(),
        CppProjectDetector(),
    )


class ProjectDetectorRegistry:
    """
    Detects every project beneath a repository root by matching each
    immediate subdirectory (and the root itself) against every
    registered `ProjectDetector`'s manifest filenames/suffixes.
    """

    def __init__(self, detectors: tuple[ProjectDetector, ...] | None = None) -> None:
        self._detectors = detectors if detectors is not None else default_project_detectors()

    def detect(self, root: Path, *, max_depth: int = 2) -> tuple[ProjectSummary, ...]:
        summaries: list[ProjectSummary] = []
        seen_manifests: set[Path] = set()

        for candidate_dir in _walk_directories(root, max_depth=max_depth):
            try:
                entries = list(candidate_dir.iterdir())
            except OSError:
                continue

            for entry in entries:
                if not entry.is_file() or entry in seen_manifests:
                    continue

                detector = self._match(entry)

                if detector is None:
                    continue

                try:
                    text = entry.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue

                summaries.append(detector.describe(entry, text))
                seen_manifests.add(entry)

        return tuple(summaries)

    def _match(self, path: Path) -> ProjectDetector | None:
        for detector in self._detectors:
            if path.name in detector.manifest_filenames():
                return detector

            if path.suffix in detector.manifest_suffixes():
                return detector

        return None


def _walk_directories(root: Path, *, max_depth: int) -> list[Path]:
    directories = [root]

    if max_depth <= 0:
        return directories

    try:
        for entry in root.iterdir():
            if entry.is_dir() and not entry.name.startswith("."):
                directories.extend(_walk_directories(entry, max_depth=max_depth - 1))
    except OSError:
        pass

    return directories


def _first_match(text: str, candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in text:
            return candidate

    return None


def _first_match_keys(mapping: dict, candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in mapping:
            return candidate

    return None
