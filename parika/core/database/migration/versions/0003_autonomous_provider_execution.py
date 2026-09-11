"""
Autonomous Provider Execution Fields

Revision ID: 0003_autonomous_provider_execution
Revises: 0002_autonomous_execution
Create Date: 2026-09-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "0003_autonomous_provider_execution"
down_revision = "0002_autonomous_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add provider_request_type column
    op.add_column(
        "autonomous_task",
        sa.Column("provider_request_type", sa.String(32), nullable=True),
        schema="execution",
    )
    op.create_index(
        "ix_autonomous_task_provider_request_type",
        "autonomous_task",
        ["provider_request_type"],
        schema="execution",
    )

    # Add task_category column
    op.add_column(
        "autonomous_task",
        sa.Column("task_category", sa.String(64), nullable=True),
        schema="execution",
    )
    op.create_index(
        "ix_autonomous_task_task_category",
        "autonomous_task",
        ["task_category"],
        schema="execution",
    )

    # Add execution_requirements column
    op.add_column(
        "autonomous_task",
        sa.Column("execution_requirements", JSONB(), nullable=True),
        schema="execution",
    )


def downgrade() -> None:
    op.drop_index("ix_autonomous_task_task_category", "autonomous_task", schema="execution")
    op.drop_index("ix_autonomous_task_provider_request_type", "autonomous_task", schema="execution")
    op.drop_column("autonomous_task", "execution_requirements", schema="execution")
    op.drop_column("autonomous_task", "task_category", schema="execution")
    op.drop_column("autonomous_task", "provider_request_type", schema="execution")