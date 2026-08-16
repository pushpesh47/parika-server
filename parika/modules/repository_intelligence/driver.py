"""
PARIKA Repository Intelligence Module - Driver

Implements the ModuleDriver contract for the Repository Intelligence
Module.

On start(), registers `RepositoryKnowledgeEngine` with
`KnowledgeManager` via its public `register_engine()` API -- the same
"communicate through a Core service" pattern the Knowledge Indexing
Module already uses. Never touches `KnowledgeStorage` directly.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from parika.core.event_bus.event_bus import EventBus
from parika.core.health_manager.health_check_result import HealthCheckResult
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.knowledge_manager.knowledge_manager import KnowledgeManager
from parika.core.knowledge_manager.knowledge_source import KnowledgeSource
from parika.core.knowledge_manager.source_kind import KnowledgeSourceKind
from parika.core.knowledge_manager.source_status import KnowledgeSourceStatus
from parika.core.logger.logger import Logger
from parika.core.module_manager.driver import ModuleDriver
from parika.core.tool_manager.tool_manager import ToolManager
from parika.core.utilities.progress import ProgressReporter
from parika.modules._shared.content_hash import compute_content_hash
from parika.modules.repository_intelligence.config import (
    load_repository_intelligence_config,
)
from parika.modules.repository_intelligence.indexing.repository_knowledge_engine import (
    INDEXABLE_SUFFIXES,
    RepositoryKnowledgeEngine,
)
from parika.modules.repository_intelligence.repository.git_reader import GitReader
from parika.tools.coding.analyzers.registry import LanguageAnalyzerRegistry
from parika.tools.coding.storage import CodingIndexStorage

MODULE_HEALTH_COMPONENT_ID = "module.repository_intelligence"


class RepositoryIntelligenceModuleDriver(ModuleDriver):
    """
    Runtime driver for the Repository Intelligence Module.
    """

    def __init__(
        self,
        *,
        knowledge_manager: KnowledgeManager,
        coding_storage: CodingIndexStorage,
        analyzer_registry: LanguageAnalyzerRegistry,
        max_file_size_bytes: int,
        tool_manager: ToolManager,
        logger: Logger,
        event_bus: EventBus | None = None,
        health_manager: HealthManager | None = None,
        configuration=None,
    ) -> None:
        self._knowledge_manager = knowledge_manager
        self._coding_storage = coding_storage
        self._max_file_size_bytes = max_file_size_bytes
        self._tool_manager = tool_manager
        self._health_manager = health_manager
        self._logger = logger.get_logger(__name__)

        config = load_repository_intelligence_config(configuration)
        self._enabled = config.enabled
        self._ignored_directories = config.ignored_directories

        self.git_reader = GitReader(tool_manager)
        self._engine = RepositoryKnowledgeEngine(
            coding_storage=coding_storage,
            analyzer_registry=analyzer_registry,
            knowledge_manager=knowledge_manager,
            max_file_size_bytes=max_file_size_bytes,
            ignored_directories=config.ignored_directories,
            progress_reporter=(
                ProgressReporter(event_bus, "repository_intelligence.index_workspace")
                if event_bus is not None
                else None
            ),
        )

    @property
    def engine(self) -> RepositoryKnowledgeEngine:
        return self._engine

    def start(self) -> None:
        if not self._enabled:
            self._logger.info(
                "Repository Intelligence module is disabled by "
                "configuration; not registering its engine."
            )
            return

        self._knowledge_manager.register_engine(self._engine)

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID, check=self._check_health
            )

        self._logger.info("Repository Intelligence module started.")

    def stop(self) -> None:
        if not self._enabled:
            return

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        self._knowledge_manager.unregister_engine(self._engine)

        self._logger.info("Repository Intelligence module stopped.")

    def index_workspace(self, location: str) -> bool:
        """
        Ensure a `WORKSPACE` `KnowledgeSource` exists for `location`
        and index it only if its content changed since the last pass
        (content-hash-gated, see
        docs/development/Module_Guide.md
        section 7.3).

        Returns:
            `True` if indexing ran; `False` if skipped because the
            content hash was unchanged.
        """

        root = Path(location)
        existing = next(
            (
                source
                for source in self._knowledge_manager.get_sources()
                if source.kind is KnowledgeSourceKind.WORKSPACE
                and source.location == str(root)
            ),
            None,
        )

        if existing is None:
            source_id = uuid4()
            self._knowledge_manager.register_source(
                KnowledgeSource(
                    id=source_id,
                    name=root.name or str(root),
                    kind=KnowledgeSourceKind.WORKSPACE,
                    location=str(root),
                    status=KnowledgeSourceStatus.AVAILABLE,
                )
            )
        else:
            source_id = existing.id

        files = [
            path
            for path in _iter_indexable_files(root, self._ignored_directories)
        ]
        content_hash = compute_content_hash(files)

        return self._knowledge_manager.index_incremental(source_id, content_hash)

    def _check_health(self) -> HealthCheckResult:
        return HealthCheckResult(status=HealthStatus.HEALTHY)


def _iter_indexable_files(root: Path, ignored_directories: tuple[str, ...]) -> list[Path]:
    from parika.modules._shared.content_hash import iter_files

    return [
        path
        for path in iter_files(root, suffixes=INDEXABLE_SUFFIXES)
        if not any(part in ignored_directories for part in path.parts)
    ]
