"""
PARIKA Knowledge Manager

Public exports for the KnowledgeManager component.
"""

from .engine import KnowledgeEngine
from .events import (
    KnowledgeIndexedEvent,
    KnowledgeIndexRemovedEvent,
    KnowledgeSourceRegisteredEvent,
    KnowledgeSourceRemovedEvent,
    KnowledgeSourceUpdatedEvent,
)
from .exceptions import (
    InvalidKnowledgeError,
    InvalidKnowledgeSourceError,
    InvalidSearchQueryError,
    InvalidSearchResultError,
    KnowledgeEngineAlreadyExistsError,
    KnowledgeEngineError,
    KnowledgeEngineNotFoundError,
    KnowledgeError,
    KnowledgeIndexError,
    KnowledgeSearchError,
    KnowledgeSourceAlreadyExistsError,
    KnowledgeSourceDisabledError,
    KnowledgeSourceError,
    KnowledgeSourceNotFoundError,
    KnowledgeStorageError,
    SearchQueryError,
)
from .knowledge import Knowledge
from .knowledge_manager import KnowledgeManager
from .knowledge_source import KnowledgeSource
from .registry import KnowledgeEngineRegistry
from .search_query import SearchQuery
from .search_result import SearchResult
from .source_kind import KnowledgeSourceKind
from .source_status import KnowledgeSourceStatus
from .storage import KnowledgeStorage

__all__ = [
    "InvalidKnowledgeError",
    "InvalidKnowledgeSourceError",
    "InvalidSearchQueryError",
    "InvalidSearchResultError",
    "Knowledge",
    "KnowledgeEngine",
    "KnowledgeEngineAlreadyExistsError",
    "KnowledgeEngineError",
    "KnowledgeEngineNotFoundError",
    "KnowledgeEngineRegistry",
    "KnowledgeError",
    "KnowledgeIndexError",
    "KnowledgeIndexedEvent",
    "KnowledgeIndexRemovedEvent",
    "KnowledgeManager",
    "KnowledgeSearchError",
    "KnowledgeSource",
    "KnowledgeSourceAlreadyExistsError",
    "KnowledgeSourceDisabledError",
    "KnowledgeSourceError",
    "KnowledgeSourceKind",
    "KnowledgeSourceNotFoundError",
    "KnowledgeSourceRegisteredEvent",
    "KnowledgeSourceRemovedEvent",
    "KnowledgeSourceStatus",
    "KnowledgeSourceUpdatedEvent",
    "KnowledgeStorage",
    "KnowledgeStorageError",
    "SearchQuery",
    "SearchQueryError",
    "SearchResult",
]