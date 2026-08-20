"""
PARIKA Knowledge Indexing Module - Driver

Implements the ModuleDriver contract for the Knowledge Indexing Module.

On start(), registers the DocumentKnowledgeEngine and CodeKnowledgeEngine
with KnowledgeManager via its public `register_engine()` API -- exactly
the same "communicate through a Core service" pattern every other
Module in this codebase already uses (see
docs/architecture/Intelligence_Foundation_Design.md section 5.3). This
driver never bypasses KnowledgeManager: it never touches
KnowledgeStorage directly and never indexes anything itself.
"""

from __future__ import annotations

from pathlib import Path

from parika.core.health_manager.health_check_result import HealthCheckResult
from parika.core.health_manager.health_manager import HealthManager
from parika.core.health_manager.health_status import HealthStatus
from parika.core.knowledge_manager.knowledge_manager import KnowledgeManager
from parika.core.logger.logger import Logger
from parika.core.module_manager.driver import ModuleDriver

from .code_engine import CodeKnowledgeEngine
from .document_engine import DocumentKnowledgeEngine
from .postgresql_unit_storage import PostgreSQLKnowledgeUnitStorage

MODULE_HEALTH_COMPONENT_ID = "module.knowledge_indexing"


class KnowledgeIndexingModuleDriver(ModuleDriver):
    """
    Runtime driver for the Knowledge Indexing Module.
    """

    def __init__(
        self,
        *,
        knowledge_manager: KnowledgeManager,
        logger: Logger,
        database_path: Path,
        health_manager: HealthManager | None = None,
    ) -> None:
        self._knowledge_manager = knowledge_manager
        self._health_manager = health_manager
        self._logger = logger.get_logger(__name__)
        self._unit_storage = PostgreSQLKnowledgeUnitStorage(database_path)
        self._document_engine = DocumentKnowledgeEngine(self._unit_storage)
        self._code_engine = CodeKnowledgeEngine(self._unit_storage)

    def start(self) -> None:
        """Start the module: open unit storage and register both engines."""

        self._unit_storage.initialize()

        self._knowledge_manager.register_engine(self._document_engine)
        self._knowledge_manager.register_engine(self._code_engine)

        if self._health_manager is not None:
            self._health_manager.register(
                MODULE_HEALTH_COMPONENT_ID, check=self._check_health
            )

        self._logger.info("Knowledge Indexing module started.")

    def stop(self) -> None:
        """Stop the module: unregister both engines and close unit storage."""

        if self._health_manager is not None:
            self._health_manager.unregister(MODULE_HEALTH_COMPONENT_ID)

        self._knowledge_manager.unregister_engine(self._document_engine)
        self._knowledge_manager.unregister_engine(self._code_engine)

        self._unit_storage.shutdown()

        self._logger.info("Knowledge Indexing module stopped.")

    def _check_health(self) -> HealthCheckResult:
        return HealthCheckResult(status=HealthStatus.HEALTHY)
