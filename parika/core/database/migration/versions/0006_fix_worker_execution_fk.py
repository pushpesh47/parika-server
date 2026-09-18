"""
Fix Worker/Execution Circular FK

Revision ID: 0006_fix_worker_execution_fk
Revises: 0005_autonomous_execution_audit
Create Date: 2026-09-18

Makes execution.worker_id nullable to resolve circular FK dependency.
Worker.execution_id remains NOT NULL (worker must have an execution).
Execution can exist before worker is assigned.
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_fix_worker_execution_fk"
down_revision = "0005_autonomous_execution_audit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the existing FK constraint on execution.worker_id
    op.drop_constraint("fk_execution_worker_id", "execution", schema="execution", type_="foreignkey")
    
    # Alter column to be nullable
    op.alter_column("execution", "worker_id", 
                    existing_type=sa.String(64), 
                    nullable=True,
                    schema="execution")
    
    # Recreate FK as nullable (allows NULL, but if set must reference valid worker)
    op.create_foreign_key(
        "fk_execution_worker_id",
        "execution",
        "worker",
        ["worker_id"],
        ["id"],
        source_schema="execution",
        referent_schema="execution",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Drop the nullable FK
    op.drop_constraint("fk_execution_worker_id", "execution", schema="execution", type_="foreignkey")
    
    # Set any NULL worker_ids to a placeholder (for downgrade only)
    op.execute("UPDATE execution.execution SET worker_id = '00000000000000000000000000000000' WHERE worker_id IS NULL")
    
    # Alter column back to NOT NULL
    op.alter_column("execution", "worker_id",
                    existing_type=sa.String(64),
                    nullable=False,
                    schema="execution")
    
    # Recreate FK as NOT NULL with CASCADE
    op.create_foreign_key(
        "fk_execution_worker_id",
        "execution",
        "worker",
        ["worker_id"],
        ["id"],
        source_schema="execution",
        referent_schema="execution",
        ondelete="CASCADE",
    )
