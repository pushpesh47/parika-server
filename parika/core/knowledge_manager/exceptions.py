"""
PARIKA Knowledge Manager Exceptions.

Defines the exception hierarchy for the KnowledgeManager component.
"""

from __future__ import annotations


class KnowledgeError(Exception):
    """Base exception for the KnowledgeManager component."""


#
# Knowledge Source Exceptions
#
class KnowledgeSourceError(KnowledgeError):
    """Base exception for knowledge source errors."""


class KnowledgeSourceAlreadyExistsError(KnowledgeSourceError):
    """Raised when attempting to register an existing knowledge source."""


class KnowledgeSourceNotFoundError(KnowledgeSourceError):
    """Raised when a knowledge source cannot be found."""


class InvalidKnowledgeSourceError(KnowledgeSourceError):
    """Raised when a knowledge source is invalid."""


class KnowledgeSourceDisabledError(KnowledgeSourceError):
    """Raised when an operation requires an enabled knowledge source."""


class InvalidKnowledgeError(KnowledgeError):
    """Raised when a knowledge object is invalid."""


#
# Search Query Exceptions
#
class SearchQueryError(KnowledgeError):
    """Base exception for search query errors."""


class InvalidSearchQueryError(SearchQueryError):
    """Raised when a search query is invalid."""


class InvalidSearchResultError(KnowledgeError):
    """Raised when a search result is invalid."""


#
# Engine Exceptions
#
class KnowledgeEngineError(KnowledgeError):
    """Base exception for knowledge engine errors."""


class KnowledgeIndexError(KnowledgeEngineError):
    """Raised when indexing fails."""


class KnowledgeSearchError(KnowledgeEngineError):
    """Raised when search execution fails."""


class KnowledgeEngineAlreadyExistsError(KnowledgeEngineError):
    """Raised when a knowledge engine is already registered."""


class KnowledgeEngineNotFoundError(KnowledgeEngineError):
    """Raised when a knowledge engine cannot be found."""


#
# Storage Exceptions
#
class KnowledgeStorageError(KnowledgeError):
    """Raised when knowledge source storage operations fail."""