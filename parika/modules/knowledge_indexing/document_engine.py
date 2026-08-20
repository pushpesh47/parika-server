"""
PARIKA Document Knowledge Engine

Stdlib-only KnowledgeEngine for DOCUMENTATION/DOCUMENT_COLLECTION
sources: chunks plain-text/Markdown files by paragraph and indexes each
chunk as a searchable Knowledge unit.

See docs/architecture/Intelligence_Foundation_Design.md section 5.3.
"""

from __future__ import annotations

from pathlib import Path

from parika.core.knowledge_manager.engine import KnowledgeEngine
from parika.core.knowledge_manager.knowledge_source import KnowledgeSource
from parika.core.knowledge_manager.search_query import SearchQuery
from parika.core.knowledge_manager.search_result import SearchResult
from parika.core.knowledge_manager.source_kind import KnowledgeSourceKind
from parika.modules._shared.content_hash import iter_files
from .postgresql_unit_storage import PostgreSQLKnowledgeUnitStorage, build_knowledge_unit

_SUPPORTED_KINDS = (
    KnowledgeSourceKind.DOCUMENTATION,
    KnowledgeSourceKind.DOCUMENT_COLLECTION,
)
_DOCUMENT_SUFFIXES = (".md", ".txt", ".rst")
_MIN_CHUNK_LENGTH = 8


class DocumentKnowledgeEngine(KnowledgeEngine):
    """
    Indexes plain-text/Markdown documentation by paragraph.
    """

    def __init__(self, unit_storage: PostgreSQLKnowledgeUnitStorage) -> None:
        self._unit_storage = unit_storage

    def supports(self, source: KnowledgeSource) -> bool:
        return source.kind in _SUPPORTED_KINDS

    def index(self, source: KnowledgeSource) -> int:
        root = Path(source.location)
        units = []

        for path in iter_files(root, suffixes=_DOCUMENT_SUFFIXES):
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue

            for index, paragraph in enumerate(_split_paragraphs(text)):
                if len(paragraph) < _MIN_CHUNK_LENGTH:
                    continue

                units.append(
                    build_knowledge_unit(
                        source_id=source.id,
                        title=_title_for(paragraph, path.name),
                        content=paragraph,
                        location=f"{path}#{index}",
                    )
                )

        return self._unit_storage.replace_units_for_source(source.id, units)

    def remove(self, source: KnowledgeSource) -> None:
        self._unit_storage.delete_units_for_source(source.id)

    def search(
        self, sources: tuple[KnowledgeSource, ...], query: SearchQuery
    ) -> tuple[SearchResult, ...]:
        return self._unit_storage.search(
            source_ids=frozenset(source.id for source in sources),
            text=query.text,
            limit=query.limit + query.offset,
        )


def _split_paragraphs(text: str) -> list[str]:
    return [p.strip() for p in text.split("\n\n") if p.strip()]


def _title_for(paragraph: str, fallback: str) -> str:
    first_line = paragraph.splitlines()[0].strip("# ").strip()
    return first_line[:120] if first_line else fallback
