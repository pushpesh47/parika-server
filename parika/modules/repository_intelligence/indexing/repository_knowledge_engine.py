"""
PARIKA Repository Intelligence - Repository Knowledge Engine

A new `KnowledgeEngine` implementation supporting the *already
existing* `KnowledgeSourceKind.REPOSITORY`/`.WORKSPACE` -- no change
to `KnowledgeManager`, `KnowledgeSource`, `KnowledgeSourceKind`,
`KnowledgeStorage`, or `registry.py` is required. See
docs/development/Module_Guide.md section
6.1.

`index()`:

1. Discovers every repository/project beneath the source's location
   (`discover_workspace()`).
2. Parses and stores every discovered source file's index directly
   into the Coding Tool's own `CodingIndexStorage` (a plain library
   import, not a Module-to-Module dependency -- see section 5.6).
3. Registers each discovered README as its own child
   `KnowledgeSource(kind=DOCUMENTATION)`, letting the existing,
   unmodified `DocumentKnowledgeEngine` index it -- the entire "README
   understanding" requirement.
4. Reports its own real progress via a `ProgressReporter` tree
   (Addendum A/B).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

from parika.core.knowledge_manager.engine import KnowledgeEngine
from parika.core.knowledge_manager.knowledge import Knowledge
from parika.core.knowledge_manager.knowledge_manager import KnowledgeManager
from parika.core.knowledge_manager.knowledge_source import KnowledgeSource
from parika.core.knowledge_manager.search_query import SearchQuery
from parika.core.knowledge_manager.search_result import SearchResult
from parika.core.knowledge_manager.source_kind import KnowledgeSourceKind
from parika.core.knowledge_manager.source_status import KnowledgeSourceStatus
from parika.core.utilities.progress import NullProgressReporter, ProgressReporter
from parika.modules._shared.content_hash import compute_content_hash, iter_files
from parika.modules.repository_intelligence.indexing.project_detector import (
    ProjectDetectorRegistry,
)
from parika.modules.repository_intelligence.workspace.discovery import (
    DEFAULT_IGNORED_DIRECTORIES,
    discover_workspace,
)
from parika.modules.repository_intelligence.workspace.workspace_model import (
    WorkspaceSnapshot,
)
from parika.tools.coding.analyzers.registry import LanguageAnalyzerRegistry
from parika.tools.coding.driver_support import ensure_indexed
from parika.tools.coding.postgresql_storage import PostgreSQLCodingIndexStorage

_SUPPORTED_KINDS = (
    KnowledgeSourceKind.REPOSITORY,
    KnowledgeSourceKind.WORKSPACE,
)

INDEXABLE_SUFFIXES: tuple[str, ...] = (
    ".py", ".js", ".jsx", ".mjs", ".ts", ".tsx", ".java", ".kt", ".go",
    ".rs", ".c", ".h", ".cpp", ".cc", ".hpp", ".cs", ".php", ".sh",
    ".bash", ".ps1", ".sql", ".html", ".css",
)


class RepositoryKnowledgeEngine(KnowledgeEngine):
    """
    Indexes REPOSITORY/WORKSPACE sources: every source file's symbols
    (via the Coding Tool's own index) and every README (via the
    existing Document Knowledge Engine).
    """

    def __init__(
        self,
        *,
        coding_storage: PostgreSQLCodingIndexStorage,
        analyzer_registry: LanguageAnalyzerRegistry,
        knowledge_manager: KnowledgeManager,
        max_file_size_bytes: int,
        ignored_directories: tuple[str, ...] = DEFAULT_IGNORED_DIRECTORIES,
        project_detector_registry: ProjectDetectorRegistry | None = None,
        progress_reporter: ProgressReporter | None = None,
    ) -> None:
        self._coding_storage = coding_storage
        self._analyzer_registry = analyzer_registry
        self._knowledge_manager = knowledge_manager
        self._max_file_size_bytes = max_file_size_bytes
        self._ignored_directories = ignored_directories
        self._project_detector_registry = (
            project_detector_registry or ProjectDetectorRegistry()
        )
        self._progress = (
            progress_reporter
            if progress_reporter is not None
            else NullProgressReporter("repository_intelligence.index_workspace")
        )

    def supports(self, source: KnowledgeSource) -> bool:
        return source.kind in _SUPPORTED_KINDS

    def index(self, source: KnowledgeSource) -> int:
        root = Path(source.location)

        self._progress.started(message="Understanding workspace...")

        try:
            discovery_progress = self._progress.child(
                "repository_intelligence.discover_workspace"
            )
            discovery_progress.started(message="Discovering repositories...")

            try:
                snapshot = discover_workspace(
                    root, ignored_directories=self._ignored_directories
                )

            except Exception as ex:
                discovery_progress.failed(message=str(ex))
                raise

            discovery_progress.completed(
                message=f"Discovered {len(snapshot.repositories)} repositor"
                f"{'y' if len(snapshot.repositories) == 1 else 'ies'}."
            )

            total_symbols = 0

            for repository in snapshot.repositories:
                repository_progress = self._progress.child(
                    "repository_intelligence.index_repository"
                )
                repository_progress.started(
                    message="Understanding repository...",
                    repository=str(repository.root),
                )

                try:
                    total_symbols += self._index_repository(
                        repository.root, repository_progress
                    )

                    if repository.readme_path is not None:
                        self._ensure_readme_indexed(repository.readme_path)

                except Exception as ex:
                    repository_progress.failed(message=str(ex))
                    raise

                repository_progress.completed(message="Completed.")

        except Exception as ex:
            self._progress.failed(message=str(ex))
            raise

        self._progress.completed(message="Completed.")

        return total_symbols

    def remove(self, source: KnowledgeSource) -> None:
        root = Path(source.location)

        for path in iter_files(root, suffixes=INDEXABLE_SUFFIXES):
            self._coding_storage.delete_file(str(path))

    def search(
        self, sources: tuple[KnowledgeSource, ...], query: SearchQuery
    ) -> tuple[SearchResult, ...]:
        symbols = self._coding_storage.search(query.text, limit=query.limit + query.offset)
        source_id = sources[0].id if sources else uuid4()

        return tuple(
            SearchResult(
                knowledge=Knowledge(
                    id=uuid4(),
                    source_id=source_id,
                    title=symbol.qualified_name,
                    content=(symbol.signature or symbol.name)
                    + (f"\n\n{symbol.docstring}" if symbol.docstring else ""),
                    location=f"{symbol.file_path}:{symbol.line_start}",
                    metadata={"symbol_kind": symbol.kind.value},
                ),
                score=1.0,
            )
            for symbol in symbols
        )

    def discover(self, location: str) -> WorkspaceSnapshot:
        """
        Public, read-only convenience wrapper around `discover_workspace()`
        for callers (e.g. the Coding Agent) that need the structural
        snapshot without triggering a full re-index.
        """

        return discover_workspace(
            Path(location), ignored_directories=self._ignored_directories
        )

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _index_repository(self, repository_root: Path, progress: ProgressReporter) -> int:
        files = [
            path
            for path in iter_files(repository_root, suffixes=INDEXABLE_SUFFIXES)
            if not any(part in self._ignored_directories for part in path.parts)
        ]

        scan_progress = progress.child("coding.index.scan_files")
        scan_progress.started(message="Scanning files...")

        symbol_count = 0

        try:
            for index, path in enumerate(files, start=1):
                try:
                    parsed = ensure_indexed(
                        self._coding_storage,
                        self._analyzer_registry,
                        path,
                        max_file_size_bytes=self._max_file_size_bytes,
                    )
                    symbol_count += len(parsed.symbols)
                except Exception:
                    continue

                if index % 25 == 0 or index == len(files):
                    scan_progress.progress(
                        current=index, total=len(files), message="Scanning files..."
                    )

        except Exception as ex:
            scan_progress.failed(message=str(ex))
            raise

        scan_progress.completed(message="Completed.")

        return symbol_count

    def _ensure_readme_indexed(self, readme_path: Path) -> None:
        existing = next(
            (
                source
                for source in self._knowledge_manager.get_sources()
                if source.kind is KnowledgeSourceKind.DOCUMENTATION
                and source.location == str(readme_path)
            ),
            None,
        )

        content_hash = compute_content_hash([readme_path])
        readme_progress = self._progress.child("repository_intelligence.readme")
        readme_progress.started(message="Reading README...")

        try:
            if existing is None:
                source_id: UUID = uuid4()
                self._knowledge_manager.register_source(
                    KnowledgeSource(
                        id=source_id,
                        name=readme_path.name,
                        kind=KnowledgeSourceKind.DOCUMENTATION,
                        location=str(readme_path),
                        status=KnowledgeSourceStatus.AVAILABLE,
                    )
                )
            else:
                source_id = existing.id

            self._knowledge_manager.index_incremental(source_id, content_hash)

        except Exception as ex:
            readme_progress.failed(message=str(ex))
            raise

        readme_progress.completed(message="Completed.")
