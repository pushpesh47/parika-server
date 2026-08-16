"""
PARIKA Knowledge Source Kind

Defines the logical categories of knowledge sources managed by the
KnowledgeManager.

The source kind represents the business classification of a knowledge
source rather than its underlying storage technology or file format.

Examples
--------
Repository:
    - PARIKA source code
    - Linux kernel
    - Laravel framework

Documentation:
    - Python documentation
    - FastAPI documentation

Document Collection:
    - PDF library
    - Markdown notes
    - Office documents

Notes
-----
KnowledgeSourceKind intentionally does NOT represent:

- File formats (PDF, Markdown, Python, HTML)
- Hosting providers (GitHub, GitLab)
- Storage technologies (Filesystem, S3, Database)

Those concerns belong to the KnowledgeSource location and metadata.
"""

from __future__ import annotations

from enum import StrEnum


class KnowledgeSourceKind(StrEnum):
    """
    Logical classification of a knowledge source.

    This enum is intentionally small and stable. It represents business
    concepts rather than implementation details.
    """

    REPOSITORY = "repository"
    """A source code repository or software project."""

    DOCUMENTATION = "documentation"
    """Structured technical or reference documentation."""

    DOCUMENT_COLLECTION = "document_collection"
    """A collection of documents managed as a single knowledge source."""

    DATABASE = "database"
    """Knowledge originating from a database."""

    API = "api"
    """Knowledge exposed through an API."""

    WORKSPACE = "workspace"
    """A mixed workspace containing multiple knowledge source types."""

    CUSTOM = "custom"
    """A custom knowledge source handled by a registered engine."""