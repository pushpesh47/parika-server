"""
Autonomous Execution Foundation Schema

Revision ID: 0002_autonomous_execution
Revises: 0001_initial
Create Date: 2026-09-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = "0002_autonomous_execution"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create execution schema
    op.execute("CREATE SCHEMA IF NOT EXISTS execution")

    # Enable required extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    # ============================================================
    # EXECUTION SCHEMA: Autonomous Execution Foundation
    # ============================================================

    # execution.mission
    op.create_table(
        "mission",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("goal", sa.Text(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        sa.Column("failure", sa.Text(), nullable=True),
        sa.Column("result", JSONB(), nullable=True),
        schema="execution",
    )
    op.create_index("ix_mission_status", "mission", ["status"], schema="execution")
    op.create_index("ix_mission_created_at", "mission", ["created_at"], schema="execution")
    op.create_index("ix_mission_updated_at", "mission", ["updated_at"], schema="execution")

    # execution.autonomous_task
    op.create_table(
        "autonomous_task",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("mission_id", sa.String(64), sa.ForeignKey("execution.mission.id", ondelete="CASCADE"), nullable=False),
        sa.Column("parent_task_id", sa.String(64), sa.ForeignKey("execution.autonomous_task.id", ondelete="SET NULL"), nullable=True),
        sa.Column("agent_id", sa.String(64), sa.ForeignKey("execution.agent_instance.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("capability_id", sa.String(256), nullable=True),
        sa.Column("inputs", JSONB(), nullable=False, server_default="{}"),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deadline", sa.DateTime(timezone=True), nullable=True),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resource_budget", JSONB(), nullable=False, server_default="{}"),
        sa.Column("checkpoint_id", sa.String(64), sa.ForeignKey("execution.checkpoint.id", ondelete="SET NULL"), nullable=True),
        sa.Column("result", JSONB(), nullable=True),
        sa.Column("failure", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        schema="execution",
    )
    op.create_index("ix_autonomous_task_mission_id", "autonomous_task", ["mission_id"], schema="execution")
    op.create_index("ix_autonomous_task_status", "autonomous_task", ["status"], schema="execution")
    op.create_index("ix_autonomous_task_parent_task_id", "autonomous_task", ["parent_task_id"], schema="execution")
    op.create_index("ix_autonomous_task_agent_id", "autonomous_task", ["agent_id"], schema="execution")
    op.create_index("ix_autonomous_task_created_at", "autonomous_task", ["created_at"], schema="execution")
    op.create_index("ix_autonomous_task_updated_at", "autonomous_task", ["updated_at"], schema="execution")
    op.create_index("ix_autonomous_task_deadline", "autonomous_task", ["deadline"], schema="execution")

    # execution.task_dependency
    op.create_table(
        "task_dependency",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("execution.autonomous_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("depends_on_task_id", sa.String(64), sa.ForeignKey("execution.autonomous_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="waiting"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("satisfied_at", sa.DateTime(timezone=True), nullable=True),
        schema="execution",
    )
    op.create_index("ix_task_dependency_task_id", "task_dependency", ["task_id"], schema="execution")
    op.create_index("ix_task_dependency_depends_on_task_id", "task_dependency", ["depends_on_task_id"], schema="execution")
    op.create_index("ix_task_dependency_status", "task_dependency", ["status"], schema="execution")
    op.execute("""
        ALTER TABLE execution.task_dependency
        ADD CONSTRAINT uq_task_dependency UNIQUE (task_id, depends_on_task_id)
    """)

    # execution.agent_instance
    op.create_table(
        "agent_instance",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("mission_id", sa.String(64), sa.ForeignKey("execution.mission.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("execution.autonomous_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_profile_id", sa.String(64), nullable=False),
        sa.Column("parent_agent_id", sa.String(64), sa.ForeignKey("execution.agent_instance.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="spawned"),
        sa.Column("runtime", sa.String(64), nullable=False, server_default="native"),
        sa.Column("permission_context", JSONB(), nullable=False, server_default="{}"),
        sa.Column("resource_budget", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", JSONB(), nullable=True),
        sa.Column("failure", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        schema="execution",
    )
    op.create_index("ix_agent_instance_mission_id", "agent_instance", ["mission_id"], schema="execution")
    op.create_index("ix_agent_instance_task_id", "agent_instance", ["task_id"], schema="execution")
    op.create_index("ix_agent_instance_parent_agent_id", "agent_instance", ["parent_agent_id"], schema="execution")
    op.create_index("ix_agent_instance_status", "agent_instance", ["status"], schema="execution")
    op.create_index("ix_agent_instance_last_heartbeat", "agent_instance", ["last_heartbeat"], schema="execution")

    # execution.worker
    op.create_table(
        "worker",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("execution.autonomous_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("execution_id", sa.String(64), sa.ForeignKey("execution.execution.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="spawned"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_activity", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_heartbeat", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_interval_seconds", sa.Float(), nullable=False, server_default="30.0"),
        sa.Column("timeout_seconds", sa.Float(), nullable=False, server_default="120.0"),
        sa.Column("result", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        schema="execution",
    )
    op.create_index("ix_worker_task_id", "worker", ["task_id"], schema="execution")
    op.create_index("ix_worker_execution_id", "worker", ["execution_id"], schema="execution")
    op.create_index("ix_worker_status", "worker", ["status"], schema="execution")
    op.create_index("ix_worker_last_heartbeat", "worker", ["last_heartbeat"], schema="execution")

    # execution.execution (execution attempts)
    op.create_table(
        "execution",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("execution.autonomous_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("worker_id", sa.String(64), sa.ForeignKey("execution.worker.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("checkpoint_id", sa.String(64), sa.ForeignKey("execution.checkpoint.id", ondelete="SET NULL"), nullable=True),
        sa.Column("result", JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        schema="execution",
    )
    op.create_index("ix_execution_task_id", "execution", ["task_id"], schema="execution")
    op.create_index("ix_execution_worker_id", "execution", ["worker_id"], schema="execution")
    op.create_index("ix_execution_status", "execution", ["status"], schema="execution")
    op.create_index("ix_execution_started_at", "execution", ["started_at"], schema="execution")

    # execution.checkpoint
    op.create_table(
        "checkpoint",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), sa.ForeignKey("execution.autonomous_task.id", ondelete="CASCADE"), nullable=False),
        sa.Column("execution_id", sa.String(64), sa.ForeignKey("execution.execution.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mission_id", sa.String(64), sa.ForeignKey("execution.mission.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.String(64), sa.ForeignKey("execution.agent_instance.id", ondelete="SET NULL"), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(32), nullable=False, server_default="creating"),
        sa.Column("state_data", JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("restored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", JSONB(), nullable=False, server_default="{}"),
        schema="execution",
    )
    op.create_index("ix_checkpoint_task_id", "checkpoint", ["task_id"], schema="execution")
    op.create_index("ix_checkpoint_execution_id", "checkpoint", ["execution_id"], schema="execution")
    op.create_index("ix_checkpoint_mission_id", "checkpoint", ["mission_id"], schema="execution")
    op.create_index("ix_checkpoint_agent_id", "checkpoint", ["agent_id"], schema="execution")
    op.create_index("ix_checkpoint_status", "checkpoint", ["status"], schema="execution")
    op.create_index("ix_checkpoint_created_at", "checkpoint", ["created_at"], schema="execution")

    # execution.world_state
    op.create_table(
        "world_state",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("active_missions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_tasks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_agents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("waiting_tasks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("blocked_tasks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_tasks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retrying_tasks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("scheduled_tasks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pending_approvals", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("active_workers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("crashed_workers", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resource_usage", JSONB(), nullable=False, server_default="{}"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        schema="execution",
    )
    op.create_index("ix_world_state_updated_at", "world_state", ["updated_at"], schema="execution")

    # execution.autonomous_event (audit trail)
    op.create_table(
        "autonomous_event",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_id", sa.String(64), nullable=False, unique=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("mission_id", sa.String(64), nullable=True),
        sa.Column("task_id", sa.String(64), nullable=True),
        sa.Column("agent_id", sa.String(64), nullable=True),
        sa.Column("execution_id", sa.String(64), nullable=True),
        sa.Column("worker_id", sa.String(64), nullable=True),
        sa.Column("parent_task_id", sa.String(64), nullable=True),
        sa.Column("parent_agent_id", sa.String(64), nullable=True),
        sa.Column("payload", JSONB(), nullable=False, server_default="{}"),
        schema="execution",
    )
    op.create_index("ix_autonomous_event_mission_id", "autonomous_event", ["mission_id"], schema="execution")
    op.create_index("ix_autonomous_event_task_id", "autonomous_event", ["task_id"], schema="execution")
    op.create_index("ix_autonomous_event_agent_id", "autonomous_event", ["agent_id"], schema="execution")
    op.create_index("ix_autonomous_event_execution_id", "autonomous_event", ["execution_id"], schema="execution")
    op.create_index("ix_autonomous_event_worker_id", "autonomous_event", ["worker_id"], schema="execution")
    op.create_index("ix_autonomous_event_event_type", "autonomous_event", ["event_type"], schema="execution")
    op.create_index("ix_autonomous_event_timestamp", "autonomous_event", ["timestamp"], schema="execution")


def downgrade() -> None:
    # Drop tables in reverse order
    op.execute("DROP SCHEMA IF EXISTS execution CASCADE")