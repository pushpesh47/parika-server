"""
PARIKA Coding Tool - Index Storage - PostgreSQL Implementation

PostgreSQL-backed persistence and lexical search for the
Coding Tool's symbol/reference/import/call-graph/annotation index.
"""

from __future__ import annotations

import json
from collections import deque
from datetime import UTC, datetime
from pathlib import Path, PurePath
from types import MappingProxyType

import psycopg
from psycopg.rows import dict_row

from parika.tools.coding.exceptions import CodingIndexNotFoundError
from parika.tools.coding.model import (
    Annotation,
    AnnotationKind,
    CallEdge,
    GraphEdge,
    GraphTraversalResult,
    ImportEdge,
    ParsedFile,
    ReferenceEdge,
    ReferenceKind,
    Symbol,
    SymbolKind,
)


def _fts5_quote_query_any(text: str) -> str:
    """Safely escape free-form text for PostgreSQL tsquery, matching any token (OR)."""
    tokens = [token for token in text.split() if token.strip()]
    if not tokens:
        return ""
    return " | ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


class PostgreSQLCodingIndexStorage:
    """PostgreSQL-backed Coding Tool index storage."""

    __slots__ = ("_pool",)

    def __init__(self, pool) -> None:
        self._pool = pool

    def initialize(self) -> None:
        """No-op: schema is managed by Alembic migrations."""
        pass

    def shutdown(self) -> None:
        """No-op: pool is managed by PoolManager."""
        pass

    def _require_connection(self):
        return self._pool.connection()

    def file_content_hash(self, file_path: str) -> str | None:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT content_hash FROM coding.coding_files WHERE path = %s",
                    (file_path,),
                )
                row = cur.fetchone()
                return row["content_hash"] if row else None

    def upsert_file(self, parsed: ParsedFile) -> int:
        """Replace every stored row for `parsed.file_path` with a freshly parsed set."""
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    file_id = self._upsert_file_row(cur, conn, parsed)
                    self._delete_file_children(cur, file_id)

                    symbol_ids_by_qualified_name: dict[str, str] = {}

                    for symbol in parsed.symbols:
                        cur.execute(
                            """
                            INSERT INTO coding.coding_symbols
                            (id, file_id, kind, name, qualified_name, signature,
                             docstring, line_start, line_end)
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (
                                symbol.id,
                                file_id,
                                symbol.kind.value,
                                symbol.name,
                                symbol.qualified_name,
                                symbol.signature,
                                symbol.docstring,
                                symbol.line_start,
                                symbol.line_end,
                            ),
                        )
                        symbol_ids_by_qualified_name[symbol.qualified_name] = symbol.id

                    for import_edge in parsed.imports:
                        cur.execute(
                            """
                            INSERT INTO coding.coding_imports
                            (file_id, imported_module, imported_symbol, line)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (
                                file_id,
                                import_edge.imported_module,
                                import_edge.imported_symbol,
                                import_edge.line,
                            ),
                        )

                    for reference in parsed.references:
                        symbol_id = self._resolve_symbol_id_by_name(cur, reference.symbol_qualified_name)
                        cur.execute(
                            """
                            INSERT INTO coding.coding_references
                            (file_id, referenced_name, symbol_id, line, "column", kind)
                            VALUES (%s, %s, %s, %s, %s, %s)
                            """,
                            (
                                file_id,
                                reference.symbol_qualified_name,
                                symbol_id,
                                reference.line,
                                reference.column,
                                reference.kind.value,
                            ),
                        )

                    for call_edge in parsed.call_edges:
                        caller_symbol_id = symbol_ids_by_qualified_name.get(
                            call_edge.caller_qualified_name
                        )
                        if caller_symbol_id is None:
                            continue

                        callee_symbol_id = self._resolve_symbol_id_by_name(
                            cur, call_edge.callee_qualified_name
                        )
                        cur.execute(
                            """
                            INSERT INTO coding.coding_call_edges
                            (caller_symbol_id, callee_name, callee_symbol_id)
                            VALUES (%s, %s, %s)
                            ON CONFLICT (caller_symbol_id, callee_name) DO NOTHING
                            """,
                            (
                                caller_symbol_id,
                                call_edge.callee_qualified_name,
                                callee_symbol_id,
                            ),
                        )

                    for annotation in parsed.annotations:
                        cur.execute(
                            """
                            INSERT INTO coding.coding_annotations (file_id, kind, text, line)
                            VALUES (%s, %s, %s, %s)
                            """,
                            (file_id, annotation.kind.value, annotation.text, annotation.line),
                        )

                    conn.commit()
                    return len(parsed.symbols)
                except psycopg.Error as ex:
                    conn.rollback()
                    raise Exception(f"Failed to store the parsed index for '{parsed.file_path}'.") from ex

    def delete_file(self, file_path: str) -> None:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                try:
                    cur.execute("SELECT id FROM coding.coding_files WHERE path = %s", (file_path,))
                    row = cur.fetchone()
                    if row is None:
                        return

                    self._delete_file_children(cur, row[0])
                    cur.execute("DELETE FROM coding.coding_files WHERE id = %s", (row[0],))
                    conn.commit()
                except psycopg.Error as ex:
                    conn.rollback()
                    raise Exception(f"Failed to remove the index for '{file_path}'.") from ex

    def symbols_for_file(self, file_path: str) -> tuple[Symbol, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT s.* FROM coding.coding_symbols s
                    JOIN coding.coding_files f ON f.id = s.file_id
                    WHERE f.path = %s
                    ORDER BY s.line_start
                    """,
                    (file_path,),
                )
                return tuple(self._row_to_symbol(row) for row in cur.fetchall())

    def find_symbol(self, qualified_name: str) -> Symbol:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "SELECT * FROM coding.coding_symbols WHERE qualified_name = %s",
                    (qualified_name,),
                )
                row = cur.fetchone()
                if row is None:
                    raise CodingIndexNotFoundError(
                        f"Symbol '{qualified_name}' was not found in the index."
                    )
                return self._row_to_symbol(row)

    def search(self, text: str, *, limit: int = 20) -> tuple[Symbol, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                query = _fts5_quote_query_any(text)
                if not query:
                    return ()

                cur.execute(
                    """
                    SELECT s.*, ts_rank_cd(s.search_vector, websearch_to_tsquery('simple', %s)) AS rank
                    FROM coding.coding_symbols s
                    WHERE s.search_vector @@ websearch_to_tsquery('simple', %s)
                    ORDER BY rank
                    LIMIT %s
                    """,
                    (text, text, limit),
                )
                return tuple(self._row_to_symbol(row) for row in cur.fetchall())

    def references_to(self, qualified_name: str) -> tuple[ReferenceEdge, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                symbol = self.find_symbol(qualified_name)
                cur.execute(
                    """
                    SELECT r.*, f.path AS file_path
                    FROM coding.coding_references r
                    JOIN coding.coding_files f ON f.id = r.file_id
                    WHERE r.symbol_id = %s OR r.referenced_name = %s
                    ORDER BY f.path, r.line
                    """,
                    (symbol.id, symbol.name),
                )
                return tuple(
                    ReferenceEdge(
                        file_path=row["file_path"],
                        symbol_qualified_name=qualified_name,
                        kind=ReferenceKind(row["kind"]),
                        line=row["line"],
                        column=row["column"],
                    )
                    for row in cur.fetchall()
                )

    def callers_of(self, qualified_name: str) -> tuple[str, ...]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                symbol = self.find_symbol(qualified_name)
                cur.execute(
                    """
                    SELECT s.qualified_name FROM coding.coding_call_edges e
                    JOIN coding.coding_symbols s ON s.id = e.caller_symbol_id
                    WHERE e.callee_symbol_id = %s
                    """,
                    (symbol.id,),
                )
                return tuple(row[0] for row in cur.fetchall())

    def callees_of(self, qualified_name: str) -> tuple[str, ...]:
        with self._pool.connection() as conn:
            with conn.cursor() as cur:
                symbol = self.find_symbol(qualified_name)
                cur.execute(
                    """
                    SELECT DISTINCT COALESCE(s.qualified_name, e.callee_name) AS name
                    FROM coding.coding_call_edges e
                    LEFT JOIN coding.coding_symbols s ON s.id = e.callee_symbol_id
                    WHERE e.caller_symbol_id = %s
                    """,
                    (symbol.id,),
                )
                return tuple(row[0] for row in cur.fetchall())

    def imports_for_file(self, file_path: str) -> tuple[ImportEdge, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT i.* FROM coding.coding_imports i
                    JOIN coding.coding_files f ON f.id = i.file_id
                    WHERE f.path = %s
                    ORDER BY i.line
                    """,
                    (file_path,),
                )
                return tuple(
                    ImportEdge(
                        file_path=file_path,
                        imported_module=row["imported_module"],
                        imported_symbol=row["imported_symbol"],
                        line=row["line"],
                    )
                    for row in cur.fetchall()
                )

    def annotations_for_file(self, file_path: str) -> tuple[Annotation, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT a.* FROM coding.coding_annotations a
                    JOIN coding.coding_files f ON f.id = a.file_id
                    WHERE f.path = %s
                    ORDER BY a.line
                    """,
                    (file_path,),
                )
                return tuple(
                    Annotation(
                        file_path=file_path,
                        kind=AnnotationKind(row["kind"]),
                        text=row["text"],
                        line=row["line"],
                    )
                    for row in cur.fetchall()
                )

    def dead_code_candidates(
        self, *, entry_point_prefixes: tuple[str, ...] = ("__main__", "test_")
    ) -> tuple[Symbol, ...]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    """
                    SELECT s.* FROM coding.coding_symbols s
                    WHERE s.kind IN ('function', 'method', 'class')
                      AND NOT EXISTS (
                          SELECT 1 FROM coding.coding_references r
                          WHERE r.symbol_id = s.id OR r.referenced_name = s.name
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM coding.coding_call_edges e
                          WHERE e.callee_symbol_id = s.id
                      )
                    """
                )
                return tuple(
                    self._row_to_symbol(row)
                    for row in cur.fetchall()
                    if not any(row["name"].startswith(prefix) for prefix in entry_point_prefixes)
                )

    def summary_for_prefix(self, root_prefix: str) -> tuple[int, int, dict[str, int]]:
        with self._pool.connection() as conn:
            with conn.cursor(row_factory=dict_row) as cur:
                like_pattern = f"{root_prefix}%"
                cur.execute(
                    "SELECT id, language FROM coding.coding_files WHERE path LIKE %s",
                    (like_pattern,),
                )
                file_rows = cur.fetchall()

                if not file_rows:
                    return 0, 0, {}

                file_ids = [row["id"] for row in file_rows]
                languages: dict[str, int] = {}

                for row in file_rows:
                    languages[row["language"]] = languages.get(row["language"], 0) + 1

                placeholders = ", ".join(["%s"] * len(file_ids))
                cur.execute(
                    f"SELECT COUNT(*) AS count FROM coding.coding_symbols WHERE file_id IN ({placeholders})",
                    file_ids,
                )
                symbol_count_row = cur.fetchone()

                return len(file_ids), symbol_count_row["count"], languages

    def graph_query(
        self,
        qualified_name: str,
        *,
        kind: str = "call",
        direction: str = "forward",
        max_depth: int = 3,
        max_nodes: int = 200,
    ) -> GraphTraversalResult:
        if kind != "call":
            raise CodingIndexNotFoundError(
                f"Graph kind '{kind}' is not supported yet; only 'call' is implemented."
            )

        visited: set[str] = {qualified_name}
        edges: list[GraphEdge] = []
        queue: deque[tuple[str, int]] = deque([(qualified_name, 0)])
        truncated = False

        while queue:
            current, depth = queue.popleft()

            if depth >= max_depth or len(visited) >= max_nodes:
                if queue:
                    truncated = True
                continue

            neighbors = (
                self.callees_of(current)
                if direction == "forward"
                else self.callers_of(current)
            )

            for neighbor in neighbors:
                edge = (
                    GraphEdge(source=current, target=neighbor, kind="call")
                    if direction == "forward"
                    else GraphEdge(source=neighbor, target=current, kind="call")
                )
                edges.append(edge)

                if neighbor not in visited:
                    if len(visited) >= max_nodes:
                        truncated = True
                        continue
                    visited.add(neighbor)
                    queue.append((neighbor, depth + 1))

        return GraphTraversalResult(
            root=qualified_name,
            nodes=tuple(sorted(visited)),
            edges=tuple(edges),
            truncated=truncated,
        )

    # Internal methods

    def _upsert_file_row(self, cur, conn, parsed: ParsedFile) -> str:
        cur.execute("SELECT id FROM coding.coding_files WHERE path = %s", (parsed.file_path,))
        existing = cur.fetchone()

        if existing is not None:
            file_id = existing[0]
            cur.execute(
                """
                UPDATE coding.coding_files
                SET language = %s, content_hash = %s, indexed_at = %s
                WHERE id = %s
                """,
                (
                    parsed.language,
                    parsed.content_hash,
                    datetime.now(UTC).isoformat(),
                    file_id,
                ),
            )
            return file_id

        file_id = parsed.file_path
        cur.execute(
            """
            INSERT INTO coding.coding_files (id, path, language, content_hash, indexed_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                file_id,
                parsed.file_path,
                parsed.language,
                parsed.content_hash,
                datetime.now(UTC).isoformat(),
            ),
        )
        return file_id

    def _delete_file_children(self, cur, file_id: str) -> None:
        cur.execute(
            "DELETE FROM coding.coding_call_edges WHERE caller_symbol_id IN "
            "(SELECT id FROM coding.coding_symbols WHERE file_id = %s)",
            (file_id,),
        )
        cur.execute("DELETE FROM coding.coding_references WHERE file_id = %s", (file_id,))
        cur.execute("DELETE FROM coding.coding_imports WHERE file_id = %s", (file_id,))
        cur.execute("DELETE FROM coding.coding_annotations WHERE file_id = %s", (file_id,))
        cur.execute("DELETE FROM coding.coding_symbols WHERE file_id = %s", (file_id,))

    def _resolve_symbol_id_by_name(self, cur, name: str) -> str | None:
        cur.execute("SELECT id FROM coding.coding_symbols WHERE name = %s LIMIT 1", (name,))
        row = cur.fetchone()
        return row[0] if row else None

    def _row_to_symbol(self, row: dict) -> Symbol:
        return Symbol(
            id=row["id"],
            file_path=self._file_path_for_symbol_row(row),
            kind=SymbolKind(row["kind"]),
            name=row["name"],
            qualified_name=row["qualified_name"],
            signature=row["signature"],
            docstring=row["docstring"],
            line_start=row["line_start"],
            line_end=row["line_end"],
        )

    def _file_path_for_symbol_row(self, row: dict) -> str:
        try:
            return str(row["id"]).split(":", 1)[0]
        except (KeyError, IndexError):
            return ""