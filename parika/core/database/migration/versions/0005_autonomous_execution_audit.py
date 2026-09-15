"""
Autonomous Execution Audit Fields and Multi-Step Support

Revision ID: 0005
Revises: 0004_skills_runtimes_messages
Create Date: 2026-09-14

Adds:
- execution_plan column to autonomous_task
- Audit fields to execution table (implementation_id, version, source, backend, env, fallback, step_index, policy, budget)
- fallback_from_execution_id self-referential FK
- preferred_runtime tracking in agent_instance metadata
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "0005_autonomous_execution_audit"
down_revision = "0004_skills_runtimes_messages"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add execution_plan column to autonomous_task
    op.add_column(
        "autonomous_task",
        sa.Column("execution_plan", JSONB, nullable=True),
        schema="execution",
    )

    # Add audit fields to execution table
    op.add_column(
        "execution",
        sa.Column("selected_implementation_id", sa.String(64), nullable=True),
        schema="execution",
    )
    op.add_column(
        "execution",
        sa.Column("implementation_version", sa.String(64), nullable=True),
        schema="execution",
    )
    op.add_column(
        "execution",
        sa.Column("implementation_source", sa.String(64), nullable=True),
        schema="execution",
    )
    op.add_column(
        "execution",
        sa.Column("execution_backend", sa.String(32), nullable=True),
        schema="execution",
    )
    op.add_column(
        "execution",
        sa.Column("required_environment", sa.String(32), nullable=True),
        schema="execution",
    )
    op.add_column(
        "execution",
        sa.Column("actual_environment", sa.String(32), nullable=True),
        schema="execution",
    )
    op.add_column(
        "execution",
        sa.Column("step_index", sa.Integer, nullable=False, default=0),
        schema="execution",
    )
    op.add_column(
        "execution",
        sa.Column("policy_decision_id", sa.String(64), nullable=True),
        schema="execution",
    )
    op.add_column(
        "execution",
        sa.Column("budget_allocation_id", sa.String(64), nullable=True),
        schema="execution",
    )
    op.add_column(
        "execution",
        sa.Column("fallback_from_execution_id", sa.String(64), nullable=True),
        schema="execution",
    )
    op.add_column(
        "execution",
        sa.Column("fallback_reason", sa.Text, nullable=True),
        schema="execution",
    )
    op.add_column(
        "execution",
        sa.Column("agent_id", sa.String(64), nullable=True),
        schema="execution",
    )

    # Add self-referential FK for fallback chain
    op.create_foreign_key(
        "fk_execution_fallback_from",
        "execution",
        "execution",
        ["fallback_from_execution_id"],
        ["id"],
        source_schema="execution",
        referent_schema="execution",
        ondelete="SET NULL",
    )

    # Add index for fallback_from
    op.create_index(
        "ix_execution_fallback_from",
        "execution",
        ["fallback_from_execution_id"],
        schema="execution",
    )

    # Add index for implementation_id
    op.create_index(
        "ix_execution_implementation_id",
        "execution",
        ["selected_implementation_id"],
        schema="execution",
    )

    # Add index for agent_id
    op.create_index(
        "ix_execution_agent_id",
        "execution",
        ["agent_id"],
        schema="execution",
    )

    # Note: preferred_runtime is stored in agent_instance.metadata JSONB
    # No schema change needed for agent_instance


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_execution_agent_id", table_name="execution", schema="execution")
    op.drop_index("ix_execution_implementation_id", table_name="execution", schema="execution")
    op.drop_index("ix_execution_fallback_from", table_name="execution", schema="execution")

    # Drop FK
    op.drop_constraint("fk_execution_fallback_from", "execution", schema="execution", type_="foreignkey")

    # Drop columns from execution
    op.drop_column("execution", "fallback_reason", schema="execution")
    op.drop_column("execution", "fallback_from_execution_id", schema="execution")
    op.drop_column("execution", "budget_allocation_id", schema="execution")
    op.drop_column("execution", "policy_decision_id", schema="execution")
    op.drop_column("execution", "step_index", schema="execution")
    op.drop_column("execution", "actual_environment", schema="execution")
    op.drop_column("execution", "required_environment", schema="execution")
    op.drop_column("execution", "execution_backend", schema="execution")
    op.drop_column("execution", "implementation_source", schema="execution")
    op.drop_column("execution", "implementation_version", schema="execution")
    op.drop_column("execution", "selected_implementation_id", schema="execution")
    op.drop_column("execution", "agent_id", schema="execution")

    # Drop execution_plan from autonomous_task
    op.drop_column("autonomous_task", "execution_plan", schema="execution")