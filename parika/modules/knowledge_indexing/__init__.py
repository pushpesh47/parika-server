"""
PARIKA Knowledge Indexing Module

Registers the built-in DocumentKnowledgeEngine and CodeKnowledgeEngine
with KnowledgeManager.
"""

from .code_engine import CodeKnowledgeEngine
from .document_engine import DocumentKnowledgeEngine
from .driver import KnowledgeIndexingModuleDriver
from .manifest import (
    KNOWLEDGE_INDEXING_MODULE_ID,
    create_knowledge_indexing_module,
)
from .postgresql_unit_storage import PostgreSQLKnowledgeUnitStorage

__all__ = [
    "CodeKnowledgeEngine",
    "DocumentKnowledgeEngine",
    "KNOWLEDGE_INDEXING_MODULE_ID",
    "KnowledgeIndexingModuleDriver",
    "PostgreSQLKnowledgeUnitStorage",
    "create_knowledge_indexing_module",
]
