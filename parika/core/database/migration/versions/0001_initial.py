"""
Initial PostgreSQL schema for PARIKA durable state.

Revision ID: 0001_initial
Revises: 
Create Date: 2026-08-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create schemas
    op.execute("CREATE SCHEMA IF NOT EXISTS core")
    op.execute("CREATE SCHEMA IF NOT EXISTS coding")
    op.execute("CREATE SCHEMA IF NOT EXISTS cache")
    op.execute("CREATE SCHEMA IF NOT EXISTS agent")
    op.execute("CREATE SCHEMA IF NOT EXISTS execution")

    # Enable required extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ============================================================
    # CORE SCHEMA: Memory, Knowledge, Experience, Sessions, Expense
    # ============================================================

    # core.memory (replaces memory.sqlite3)
    op.create_table(
        "memory",
        sa.Column("memory_id", sa.Text(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("origin", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tags", JSONB(), nullable=False, server_default="[]"),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("session_id", sa.Text(), nullable=True),
        sa.Column("importance_score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("access_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decay_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("importance", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        schema="core",
    )
    op.create_index("ix_memory_scope_session", "memory", ["scope", "session_id"], schema="core")
    op.create_index("ix_memory_kind", "memory", ["kind"], schema="core")
    op.create_index("ix_memory_category", "memory", ["category"], schema="core")
    op.create_index("ix_memory_created_at", "memory", ["created_at"], schema="core")
    op.create_index("ix_memory_decay_at", "memory", ["decay_at"], schema="core")
    # FTS: tsvector generated column + GIN index
    op.execute("""
        ALTER TABLE core.memory
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (
            to_tsvector('simple', coalesce(content, '') || ' ' || coalesce(category, ''))
        ) STORED
    """)
    op.execute("CREATE INDEX ix_memory_search_vector ON core.memory USING GIN (search_vector)")

    # core.memory_metadata (for schema versioning)
    op.create_table(
        "memory_metadata",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        schema="core",
    )

    # core.knowledge_source (replaces knowledge.sqlite3)
    op.create_table(
        "knowledge_source",
        sa.Column("id", sa.Text(), primary_key=True),  # UUID as text
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("last_indexed_at", sa.DateTime(timezone=True), nullable=True),
        schema="core",
    )
    op.create_index("ix_knowledge_source_kind", "knowledge_source", ["kind"], schema="core")
    op.create_index("ix_knowledge_source_status", "knowledge_source", ["status"], schema="core")

    # core.knowledge_source_metadata
    op.create_table(
        "knowledge_source_metadata",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        schema="core",
    )

    # core.experience (replaces experience.sqlite3)
    op.create_table(
        "experience",
        sa.Column("experience_id", sa.Text(), primary_key=True),
        sa.Column("capability_id", sa.Text(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_id", sa.Text(), nullable=True),
        sa.Column("model_id", sa.Text(), nullable=True),
        sa.Column("tool_id", sa.Text(), nullable=True),
        sa.Column("latency_ms", sa.Float(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=True),
        sa.Column("correction_of", sa.Text(), nullable=True),
        sa.Column("user_correction", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        schema="core",
    )
    op.create_index("ix_experience_capability", "experience", ["capability_id", "provider_id", "model_id"], schema="core")

    # core.experience_metadata
    op.create_table(
        "experience_metadata",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        schema="core",
    )

    # core.session (replaces sessions.sqlite3)
    op.create_table(
        "session",
        sa.Column("session_id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("workspace_path", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        schema="core",
    )
    op.create_index("ix_session_updated_at", "session", ["updated_at"], schema="core")
    # FTS for session messages (we'll populate via trigger on session_message)
    op.execute("""
        ALTER TABLE core.session
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(summary, ''))) STORED
    """)
    op.execute("CREATE INDEX ix_session_search_vector ON core.session USING GIN (search_vector)")

    # core.session_message
    op.create_table(
        "session_message",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text(), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("token_count", sa.Integer(), nullable=True),
        schema="core",
    )
    op.create_index("ix_session_message_session_id", "session_message", ["session_id"], schema="core")
    op.create_index("ix_session_message_created_at", "session_message", ["created_at"], schema="core")
    # FTS for session messages
    op.execute("""
        ALTER TABLE core.session_message
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED
    """)
    op.execute("CREATE INDEX ix_session_message_search_vector ON core.session_message USING GIN (search_vector)")

    # core.expense (replaces expense.sqlite3)
    op.create_table(
        "expense",
        sa.Column("expense_id", sa.Text(), primary_key=True),
        sa.Column("amount_minor", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("item", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        schema="core",
    )
    op.create_index("ix_expense_date", "expense", ["expense_date"], schema="core")
    op.create_index("ix_expense_category", "expense", ["category"], schema="core")
    op.create_index("ix_expense_created_at", "expense", ["created_at"], schema="core")

    # core.expense_metadata
    op.create_table(
        "expense_metadata",
        sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        schema="core",
    )

    # ============================================================
    # CODING SCHEMA: Knowledge Units, Coding Index
    # ============================================================

    # coding.knowledge_unit (replaces knowledge_units.sqlite3)
    op.create_table(
        "knowledge_unit",
        sa.Column("id", sa.Text(), primary_key=True),  # UUID as text
        sa.Column("source_id", sa.Text(), nullable=False),  # UUID as text
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("location", sa.Text(), nullable=False),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        schema="coding",
    )
    op.create_index("ix_knowledge_unit_source_id", "knowledge_unit", ["source_id"], schema="coding")
    # FTS for knowledge units
    op.execute("""
        ALTER TABLE coding.knowledge_unit
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(content, ''))) STORED
    """)
    op.execute("CREATE INDEX ix_knowledge_unit_search_vector ON coding.knowledge_unit USING GIN (search_vector)")

    # coding.coding_files
    op.create_table(
        "coding_files",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("path", sa.Text(), nullable=False, unique=True),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=False),
        schema="coding",
    )

    # coding.coding_symbols
    op.create_table(
        "coding_symbols",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("qualified_name", sa.Text(), nullable=False),
        sa.Column("signature", sa.Text(), nullable=True),
        sa.Column("docstring", sa.Text(), nullable=True),
        sa.Column("line_start", sa.Integer(), nullable=False),
        sa.Column("line_end", sa.Integer(), nullable=False),
        schema="coding",
    )
    op.create_index("ix_coding_symbols_file", "coding_symbols", ["file_id"], schema="coding")
    op.create_index("ix_coding_symbols_name", "coding_symbols", ["name"], schema="coding")
    op.create_index("ix_coding_symbols_qualified_name", "coding_symbols", ["qualified_name"], schema="coding")
    # FTS for symbols
    op.execute("""
        ALTER TABLE coding.coding_symbols
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('simple', coalesce(name, '') || ' ' || coalesce(qualified_name, '') || ' ' || coalesce(signature, '') || ' ' || coalesce(docstring, ''))) STORED
    """)
    op.execute("CREATE INDEX ix_coding_symbols_search_vector ON coding.coding_symbols USING GIN (search_vector)")

    # coding.coding_references
    op.create_table(
        "coding_references",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.Column("referenced_name", sa.Text(), nullable=False),
        sa.Column("symbol_id", sa.Text(), nullable=True),
        sa.Column("line", sa.Integer(), nullable=False),
        sa.Column("column", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        schema="coding",
    )
    op.create_index("ix_coding_references_symbol", "coding_references", ["symbol_id"], schema="coding")
    op.create_index("ix_coding_references_name", "coding_references", ["referenced_name"], schema="coding")

    # coding.coding_imports
    op.create_table(
        "coding_imports",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.Column("imported_module", sa.Text(), nullable=False),
        sa.Column("imported_symbol", sa.Text(), nullable=True),
        sa.Column("line", sa.Integer(), nullable=False),
        schema="coding",
    )
    op.create_index("ix_coding_imports_file", "coding_imports", ["file_id"], schema="coding")

    # coding.coding_call_edges
    op.create_table(
        "coding_call_edges",
        sa.Column("caller_symbol_id", sa.Text(), nullable=False),
        sa.Column("callee_name", sa.Text(), nullable=False),
        sa.Column("callee_symbol_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("caller_symbol_id", "callee_name", name="pk_coding_call_edges"),
        schema="coding",
    )
    op.create_index("ix_coding_call_edges_callee", "coding_call_edges", ["callee_symbol_id"], schema="coding")

    # coding.coding_annotations
    op.create_table(
        "coding_annotations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("file_id", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("line", sa.Integer(), nullable=False),
        schema="coding",
    )
    op.create_index("ix_coding_annotations_file", "coding_annotations", ["file_id"], schema="coding")
    # FTS for annotations
    op.execute("""
        ALTER TABLE coding.coding_annotations
        ADD COLUMN search_vector tsvector
        GENERATED ALWAYS AS (to_tsvector('simple', coalesce(text, ''))) STORED
    """)
    op.execute("CREATE INDEX ix_coding_annotations_search_vector ON coding.coding_annotations USING GIN (search_vector)")

    # ============================================================
    # CACHE SCHEMA: Weather, Web Search
    # ============================================================

    # cache.weather
    op.create_table(
        "weather",
        sa.Column("cache_key", sa.Text(), primary_key=True),
        sa.Column("response", JSONB(), nullable=False),
        sa.Column("cached_at", sa.Float(), nullable=False),  # Unix timestamp
        schema="cache",
    )

    # cache.web_search
    op.create_table(
        "web_search",
        sa.Column("cache_key", sa.Text(), primary_key=True),
        sa.Column("results", JSONB(), nullable=False),
        sa.Column("cached_at", sa.Float(), nullable=False),  # Unix timestamp
        schema="cache",
    )

    # ============================================================
    # AGENT SCHEMA (placeholder for future use)
    # ============================================================

    op.create_table(
        "agent_profile",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("specialization", sa.Text(), nullable=False),
        sa.Column("preferred_capabilities", JSONB(), nullable=False, server_default="[]"),
        sa.Column("allowed_capabilities", JSONB(), nullable=False, server_default="[]"),
        sa.Column("prohibited_capabilities", JSONB(), nullable=False, server_default="[]"),
        sa.Column("preferred_categories", JSONB(), nullable=False, server_default="[]"),
        sa.Column("allowed_categories", JSONB(), nullable=False, server_default="[]"),
        sa.Column("preferred_providers", JSONB(), nullable=False, server_default="[]"),
        sa.Column("preferred_models", JSONB(), nullable=False, server_default="[]"),
        sa.Column("model_constraints", JSONB(), nullable=False, server_default="{}"),
        sa.Column("behavioral_policies", JSONB(), nullable=False, server_default="{}"),
        sa.Column("resource_constraints", JSONB(), nullable=False, server_default="{}"),
        sa.Column("delegation_policy", sa.Text(), nullable=False, server_default="allow"),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        schema="agent",
    )

    # ============================================================
    # EXECUTION SCHEMA (placeholder for future use)
    # ============================================================

    op.create_table(
        "execution_goal",
        sa.Column("id", sa.Text(), primary_key=True),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.Column("capability_id", sa.Text(), nullable=False),
        sa.Column("inputs", JSONB(), nullable=False, server_default="{}"),
        sa.Column("context_id", sa.Text(), nullable=True),
        sa.Column("depends_on", JSONB(), nullable=False, server_default="[]"),
        sa.Column("policy_rules", JSONB(), nullable=False, server_default="[]"),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("agent_id", sa.Text(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure", sa.Text(), nullable=True),
        schema="execution",
    )
    op.create_index("ix_execution_goal_request", "execution_goal", ["request_id"], schema="execution")


def downgrade() -> None:
    # Drop tables in reverse order
    op.execute("DROP SCHEMA IF EXISTS execution CASCADE")
    op.execute("DROP SCHEMA IF EXISTS agent CASCADE")
    op.execute("DROP SCHEMA IF EXISTS cache CASCADE")
    op.execute("DROP SCHEMA IF EXISTS coding CASCADE")
    op.execute("DROP SCHEMA IF EXISTS core CASCADE")
    # Extensions are left as they may be used by other applications