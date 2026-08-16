"""
PARIKA Coding Tool - Index Storage

SQLite-backed persistence and lexical (FTS5 BM25) search for the
Coding Tool's symbol/reference/import/call-graph/annotation index
(`coding_index.sqlite3`). Owned entirely by the Coding Tool's own
Module (not Core) -- `KnowledgeManager` never sees these rows
directly, mirroring `KnowledgeUnitStorage`'s placement inside
`knowledge_indexing`, not inside `KnowledgeManager`. See
docs/development/Tool_Guide.md section
4.5.

Symbol/call/reference resolution in this store is a deliberate, coarse
heuristic (matching by plain name across the whole index), not full
semantic/type-aware resolution -- the same tier of analysis
`universal-ctags`/token-hashing tools operate at, chosen explicitly
over a full Language Server implementation (see section 4.4/23 for the
comparison).
"""

from __future__ import annotations

import sqlite3
from collections import deque
from datetime import UTC, datetime
from pathlib import Path, PurePath

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

SQLITE_BUSY_TIMEOUT_MS = 5000


def _fts5_quote_query_any(text: str) -> str:
    """
    Safely escape free-form text for an FTS5 `MATCH` query, matching
    any token (explicit OR). Identical helper/rationale to
    `parika/modules/knowledge_indexing/unit_storage.py`.
    """

    tokens = [token for token in text.split() if token.strip()]

    if not tokens:
        return ""

    return " OR ".join(f'"{token.replace(chr(34), chr(34) * 2)}"' for token in tokens)


class CodingIndexStorageError(Exception):
    """Raised when a Coding Tool index storage operation fails."""


class CodingIndexStorage:
    """
    Owns `coding_index.sqlite3`'s connection, schema, and every read/
    write query the Coding Tool's operations need.
    """

    __slots__ = ("_database_path", "_connection")

    def __init__(self, database_path: Path) -> None:
        if not isinstance(database_path, PurePath):
            raise TypeError("database_path must be a pathlib.Path object.")

        self._database_path = database_path
        self._connection: sqlite3.Connection | None = None

    def initialize(self) -> None:
        if self._connection is not None:
            return

        try:
            self._database_path.parent.mkdir(parents=True, exist_ok=True)

            connection = sqlite3.connect(database=self._database_path)
            connection.row_factory = sqlite3.Row

            connection.execute("PRAGMA journal_mode = WAL;")
            connection.execute("PRAGMA synchronous = NORMAL;")
            connection.execute(f"PRAGMA busy_timeout = {SQLITE_BUSY_TIMEOUT_MS};")

            connection.executescript(_SCHEMA)
            connection.commit()

            self._connection = connection

        except Exception:
            if self._connection is not None:
                try:
                    self._connection.close()
                finally:
                    self._connection = None
            raise

    def shutdown(self) -> None:
        if self._connection is None:
            return

        try:
            self._connection.close()
        except sqlite3.Error as ex:
            raise CodingIndexStorageError(
                "Failed to shut down the Coding Tool index storage."
            ) from ex
        finally:
            self._connection = None

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    def file_content_hash(self, file_path: str) -> str | None:
        """
        Return the stored content hash for `file_path`, or `None` if
        it has never been indexed -- used by the caller to skip
        re-parsing an unchanged file (see
        docs/development/Tool_Guide.md
        section 7.3).
        """

        connection = self._require_connection()
        row = connection.execute(
            "SELECT content_hash FROM coding_files WHERE path = ?;",
            (file_path,),
        ).fetchone()

        return row["content_hash"] if row else None

    def upsert_file(self, parsed: ParsedFile) -> int:
        """
        Replace every stored row for `parsed.file_path` with a freshly
        parsed set. Returns the number of symbols stored.
        """

        connection = self._require_connection()

        try:
            file_id = self._upsert_file_row(connection, parsed)
            self._delete_file_children(connection, file_id)

            symbol_ids_by_qualified_name: dict[str, str] = {}

            for symbol in parsed.symbols:
                connection.execute(
                    """
                    INSERT INTO coding_symbols
                    (id, file_id, kind, name, qualified_name, signature,
                     docstring, line_start, line_end)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
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
                connection.execute(
                    """
                    INSERT INTO coding_imports
                    (file_id, imported_module, imported_symbol, line)
                    VALUES (?, ?, ?, ?);
                    """,
                    (
                        file_id,
                        import_edge.imported_module,
                        import_edge.imported_symbol,
                        import_edge.line,
                    ),
                )

            for reference in parsed.references:
                symbol_id = self._resolve_symbol_id_by_name(
                    connection, reference.symbol_qualified_name
                )
                connection.execute(
                    """
                    INSERT INTO coding_references
                    (file_id, referenced_name, symbol_id, line, column, kind)
                    VALUES (?, ?, ?, ?, ?, ?);
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
                    connection, call_edge.callee_qualified_name
                )
                connection.execute(
                    """
                    INSERT OR IGNORE INTO coding_call_edges
                    (caller_symbol_id, callee_name, callee_symbol_id)
                    VALUES (?, ?, ?);
                    """,
                    (
                        caller_symbol_id,
                        call_edge.callee_qualified_name,
                        callee_symbol_id,
                    ),
                )

            for annotation in parsed.annotations:
                connection.execute(
                    """
                    INSERT INTO coding_annotations (file_id, kind, text, line)
                    VALUES (?, ?, ?, ?);
                    """,
                    (file_id, annotation.kind.value, annotation.text, annotation.line),
                )

            connection.commit()

            return len(parsed.symbols)

        except sqlite3.Error as ex:
            connection.rollback()
            raise CodingIndexStorageError(
                f"Failed to store the parsed index for '{parsed.file_path}'."
            ) from ex

    def delete_file(self, file_path: str) -> None:
        connection = self._require_connection()

        try:
            row = connection.execute(
                "SELECT id FROM coding_files WHERE path = ?;",
                (file_path,),
            ).fetchone()

            if row is None:
                return

            self._delete_file_children(connection, row["id"])
            connection.execute(
                "DELETE FROM coding_files WHERE id = ?;", (row["id"],)
            )
            connection.commit()

        except sqlite3.Error as ex:
            connection.rollback()
            raise CodingIndexStorageError(
                f"Failed to remove the index for '{file_path}'."
            ) from ex

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------

    def symbols_for_file(self, file_path: str) -> tuple[Symbol, ...]:
        connection = self._require_connection()
        rows = connection.execute(
            """
            SELECT s.* FROM coding_symbols s
            JOIN coding_files f ON f.id = s.file_id
            WHERE f.path = ?
            ORDER BY s.line_start;
            """,
            (file_path,),
        ).fetchall()

        return tuple(_row_to_symbol(row) for row in rows)

    def find_symbol(self, qualified_name: str) -> Symbol:
        connection = self._require_connection()
        row = connection.execute(
            "SELECT * FROM coding_symbols WHERE qualified_name = ?;",
            (qualified_name,),
        ).fetchone()

        if row is None:
            raise CodingIndexNotFoundError(
                f"Symbol '{qualified_name}' was not found in the index."
            )

        return _row_to_symbol(row)

    def search(self, text: str, *, limit: int = 20) -> tuple[Symbol, ...]:
        connection = self._require_connection()
        query = _fts5_quote_query_any(text)

        if not query:
            return ()

        rows = connection.execute(
            """
            SELECT s.*, bm25(coding_symbols_fts) AS rank
            FROM coding_symbols_fts
            JOIN coding_symbols s ON s.rowid = coding_symbols_fts.rowid
            WHERE coding_symbols_fts MATCH ?
            ORDER BY rank
            LIMIT ?;
            """,
            (query, limit),
        ).fetchall()

        return tuple(_row_to_symbol(row) for row in rows)

    def references_to(self, qualified_name: str) -> tuple[ReferenceEdge, ...]:
        connection = self._require_connection()
        symbol = self.find_symbol(qualified_name)

        rows = connection.execute(
            """
            SELECT r.*, f.path AS file_path
            FROM coding_references r
            JOIN coding_files f ON f.id = r.file_id
            WHERE r.symbol_id = ? OR r.referenced_name = ?
            ORDER BY f.path, r.line;
            """,
            (symbol.id, symbol.name),
        ).fetchall()

        return tuple(
            ReferenceEdge(
                file_path=row["file_path"],
                symbol_qualified_name=qualified_name,
                kind=ReferenceKind(row["kind"]),
                line=row["line"],
                column=row["column"],
            )
            for row in rows
        )

    def callers_of(self, qualified_name: str) -> tuple[str, ...]:
        connection = self._require_connection()
        symbol = self.find_symbol(qualified_name)

        rows = connection.execute(
            """
            SELECT s.qualified_name FROM coding_call_edges e
            JOIN coding_symbols s ON s.id = e.caller_symbol_id
            WHERE e.callee_symbol_id = ?;
            """,
            (symbol.id,),
        ).fetchall()

        return tuple(row["qualified_name"] for row in rows)

    def callees_of(self, qualified_name: str) -> tuple[str, ...]:
        connection = self._require_connection()
        symbol = self.find_symbol(qualified_name)

        rows = connection.execute(
            """
            SELECT DISTINCT COALESCE(s.qualified_name, e.callee_name) AS name
            FROM coding_call_edges e
            LEFT JOIN coding_symbols s ON s.id = e.callee_symbol_id
            WHERE e.caller_symbol_id = ?;
            """,
            (symbol.id,),
        ).fetchall()

        return tuple(row["name"] for row in rows)

    def imports_for_file(self, file_path: str) -> tuple[ImportEdge, ...]:
        connection = self._require_connection()
        rows = connection.execute(
            """
            SELECT i.* FROM coding_imports i
            JOIN coding_files f ON f.id = i.file_id
            WHERE f.path = ?
            ORDER BY i.line;
            """,
            (file_path,),
        ).fetchall()

        return tuple(
            ImportEdge(
                file_path=file_path,
                imported_module=row["imported_module"],
                imported_symbol=row["imported_symbol"],
                line=row["line"],
            )
            for row in rows
        )

    def annotations_for_file(self, file_path: str) -> tuple[Annotation, ...]:
        connection = self._require_connection()
        rows = connection.execute(
            """
            SELECT a.* FROM coding_annotations a
            JOIN coding_files f ON f.id = a.file_id
            WHERE f.path = ?
            ORDER BY a.line;
            """,
            (file_path,),
        ).fetchall()

        return tuple(
            Annotation(
                file_path=file_path,
                kind=AnnotationKind(row["kind"]),
                text=row["text"],
                line=row["line"],
            )
            for row in rows
        )

    def dead_code_candidates(
        self, *, entry_point_prefixes: tuple[str, ...] = ("__main__", "test_")
    ) -> tuple[Symbol, ...]:
        """
        Return every symbol with zero non-definition references,
        excluding names matching `entry_point_prefixes`. A read-only,
        deterministic candidate list -- never auto-deleted.
        """

        connection = self._require_connection()
        rows = connection.execute(
            """
            SELECT s.* FROM coding_symbols s
            WHERE s.kind IN ('function', 'method', 'class')
              AND NOT EXISTS (
                  SELECT 1 FROM coding_references r
                  WHERE r.symbol_id = s.id OR r.referenced_name = s.name
              )
              AND NOT EXISTS (
                  SELECT 1 FROM coding_call_edges e
                  WHERE e.callee_symbol_id = s.id
              );
            """
        ).fetchall()

        return tuple(
            _row_to_symbol(row)
            for row in rows
            if not any(row["name"].startswith(prefix) for prefix in entry_point_prefixes)
        )

    def summary_for_prefix(self, root_prefix: str) -> tuple[int, int, dict[str, int]]:
        """
        Return `(file_count, symbol_count, {language: file_count})` for
        every indexed file whose path starts with `root_prefix`. Used
        by `coding.project_summary`.
        """

        connection = self._require_connection()
        like_pattern = f"{root_prefix}%"

        file_rows = connection.execute(
            "SELECT id, language FROM coding_files WHERE path LIKE ?;",
            (like_pattern,),
        ).fetchall()

        if not file_rows:
            return 0, 0, {}

        file_ids = [row["id"] for row in file_rows]
        languages: dict[str, int] = {}

        for row in file_rows:
            languages[row["language"]] = languages.get(row["language"], 0) + 1

        placeholders = ", ".join("?" for _ in file_ids)
        symbol_count_row = connection.execute(
            f"SELECT COUNT(*) AS count FROM coding_symbols "
            f"WHERE file_id IN ({placeholders});",
            file_ids,
        ).fetchone()

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
        """
        Bounded-depth traversal of the call or import graph, in either
        direction. `direction="reverse"` is what `coding.impact_analysis`
        uses to answer "what would this change break."
        """

        if kind != "call":
            raise CodingIndexNotFoundError(
                f"Graph kind '{kind}' is not supported yet; only 'call' "
                "is implemented in this phase."
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

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require_connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise CodingIndexStorageError(
                "The Coding Tool index storage has not been initialized."
            )

        return self._connection

    def _upsert_file_row(
        self, connection: sqlite3.Connection, parsed: ParsedFile
    ) -> str:
        existing = connection.execute(
            "SELECT id FROM coding_files WHERE path = ?;",
            (parsed.file_path,),
        ).fetchone()

        if existing is not None:
            file_id = existing["id"]
            connection.execute(
                """
                UPDATE coding_files
                SET language = ?, content_hash = ?, indexed_at = ?
                WHERE id = ?;
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
        connection.execute(
            """
            INSERT INTO coding_files (id, path, language, content_hash, indexed_at)
            VALUES (?, ?, ?, ?, ?);
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

    def _delete_file_children(
        self, connection: sqlite3.Connection, file_id: str
    ) -> None:
        connection.execute(
            "DELETE FROM coding_call_edges WHERE caller_symbol_id IN "
            "(SELECT id FROM coding_symbols WHERE file_id = ?);",
            (file_id,),
        )
        connection.execute("DELETE FROM coding_references WHERE file_id = ?;", (file_id,))
        connection.execute("DELETE FROM coding_imports WHERE file_id = ?;", (file_id,))
        connection.execute("DELETE FROM coding_annotations WHERE file_id = ?;", (file_id,))
        connection.execute("DELETE FROM coding_symbols WHERE file_id = ?;", (file_id,))

    def _resolve_symbol_id_by_name(
        self, connection: sqlite3.Connection, name: str
    ) -> str | None:
        row = connection.execute(
            "SELECT id FROM coding_symbols WHERE name = ? LIMIT 1;",
            (name,),
        ).fetchone()

        return row["id"] if row else None


def _row_to_symbol(row: sqlite3.Row) -> Symbol:
    return Symbol(
        id=row["id"],
        file_path=_file_path_for_symbol_row(row),
        kind=SymbolKind(row["kind"]),
        name=row["name"],
        qualified_name=row["qualified_name"],
        signature=row["signature"],
        docstring=row["docstring"],
        line_start=row["line_start"],
        line_end=row["line_end"],
    )


def _file_path_for_symbol_row(row: sqlite3.Row) -> str:
    # `coding_symbols.id` is constructed as f"{path}:{line}:{kind}:{name}"
    # by every LanguageAnalyzer (see model.py); this is a defensive,
    # best-effort fallback only used when a caller queries a bare
    # `coding_symbols` row without joining `coding_files` -- every
    # storage method above that returns a Symbol already joins
    # `coding_files` when file path fidelity matters.
    try:
        return str(row["id"]).split(":", 1)[0]
    except (KeyError, IndexError):
        return ""


_SCHEMA = """
CREATE TABLE IF NOT EXISTS coding_files (
    id TEXT PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,
    language TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    indexed_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS coding_symbols (
    id TEXT PRIMARY KEY,
    file_id TEXT NOT NULL REFERENCES coding_files(id),
    kind TEXT NOT NULL,
    name TEXT NOT NULL,
    qualified_name TEXT NOT NULL,
    signature TEXT NULL,
    docstring TEXT NULL,
    line_start INTEGER NOT NULL,
    line_end INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coding_symbols_file ON coding_symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_coding_symbols_name ON coding_symbols(name);
CREATE INDEX IF NOT EXISTS idx_coding_symbols_qualified_name
    ON coding_symbols(qualified_name);

CREATE VIRTUAL TABLE IF NOT EXISTS coding_symbols_fts USING fts5(
    name, qualified_name, signature, docstring,
    content='coding_symbols', content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS coding_symbols_ai
AFTER INSERT ON coding_symbols BEGIN
    INSERT INTO coding_symbols_fts(rowid, name, qualified_name, signature, docstring)
    VALUES (new.rowid, new.name, new.qualified_name, new.signature, new.docstring);
END;
CREATE TRIGGER IF NOT EXISTS coding_symbols_ad
AFTER DELETE ON coding_symbols BEGIN
    INSERT INTO coding_symbols_fts(coding_symbols_fts, rowid, name, qualified_name, signature, docstring)
    VALUES ('delete', old.rowid, old.name, old.qualified_name, old.signature, old.docstring);
END;

CREATE TABLE IF NOT EXISTS coding_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL REFERENCES coding_files(id),
    referenced_name TEXT NOT NULL,
    symbol_id TEXT NULL REFERENCES coding_symbols(id),
    line INTEGER NOT NULL,
    column INTEGER NOT NULL,
    kind TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coding_references_symbol ON coding_references(symbol_id);
CREATE INDEX IF NOT EXISTS idx_coding_references_name ON coding_references(referenced_name);

CREATE TABLE IF NOT EXISTS coding_imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL REFERENCES coding_files(id),
    imported_module TEXT NOT NULL,
    imported_symbol TEXT NULL,
    line INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_coding_imports_file ON coding_imports(file_id);

CREATE TABLE IF NOT EXISTS coding_call_edges (
    caller_symbol_id TEXT NOT NULL REFERENCES coding_symbols(id),
    callee_name TEXT NOT NULL,
    callee_symbol_id TEXT NULL REFERENCES coding_symbols(id),
    PRIMARY KEY (caller_symbol_id, callee_name)
);
CREATE INDEX IF NOT EXISTS idx_call_edges_callee ON coding_call_edges(callee_symbol_id);

CREATE TABLE IF NOT EXISTS coding_annotations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id TEXT NOT NULL REFERENCES coding_files(id),
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    line INTEGER NOT NULL
);
CREATE VIRTUAL TABLE IF NOT EXISTS coding_annotations_fts USING fts5(
    text, content='coding_annotations', content_rowid='rowid'
);
CREATE TRIGGER IF NOT EXISTS coding_annotations_ai
AFTER INSERT ON coding_annotations BEGIN
    INSERT INTO coding_annotations_fts(rowid, text) VALUES (new.rowid, new.text);
END;
CREATE TRIGGER IF NOT EXISTS coding_annotations_ad
AFTER DELETE ON coding_annotations BEGIN
    INSERT INTO coding_annotations_fts(coding_annotations_fts, rowid, text)
    VALUES ('delete', old.rowid, old.text);
END;
"""
