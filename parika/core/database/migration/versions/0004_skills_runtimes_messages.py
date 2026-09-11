"""
PARIKA Phase 2 Migration: Skills, Runtimes, Agent Communication, Wait Conditions

Adds tables for:
- skill: Agent Skills with metadata and trust state
- skill_source: Skill sources (PARIKA local, user installed, community, Hermes, remote)
- skill_security_record: Security scan records for skills
- capability_implementation: Multiple implementations per semantic capability
- agent_message: Durable agent-to-agent messages
- runtime_profile: Runtime configurations
- wait_condition: Durable wait conditions for event-driven autonomy
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '0004_skills_runtimes_messages'
down_revision = '0003_autonomous_provider_execution'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create execution schema if not exists (should already exist from Phase 1)
    op.execute('CREATE SCHEMA IF NOT EXISTS execution')

    # skill table
    op.create_table(
        'skill',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('source_id', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('version', sa.Text(), nullable=False),
        sa.Column('author', sa.Text(), nullable=True, default=''),
        sa.Column('license', sa.Text(), nullable=True, default=''),
        sa.Column('platforms', postgresql.JSONB(), nullable=True, default=[]),
        sa.Column('tags', postgresql.JSONB(), nullable=True, default=[]),
        sa.Column('related_skills', postgresql.JSONB(), nullable=True, default=[]),
        sa.Column('compatibility', postgresql.JSONB(), nullable=True, default={}),
        sa.Column('allowed_tools', postgresql.JSONB(), nullable=True, default=[]),
        sa.Column('required_capabilities', postgresql.JSONB(), nullable=True, default=[]),
        sa.Column('required_skills', postgresql.JSONB(), nullable=True, default=[]),
        sa.Column('hermes_tags', postgresql.JSONB(), nullable=True, default=[]),
        sa.Column('hermes_related_skills', postgresql.JSONB(), nullable=True, default=[]),
        sa.Column('path', sa.Text(), nullable=False),
        sa.Column('status', sa.Text(), nullable=False, default='discovered'),
        sa.Column('trust_state', sa.Text(), nullable=False, default='discovered'),
        sa.Column('security_status', sa.Text(), nullable=False, default='pending'),
        sa.Column('security_record_id', sa.Text(), nullable=True),
        sa.Column('content_hash', sa.Text(), nullable=False, default=''),
        sa.Column('body', sa.Text(), nullable=True),
        sa.Column('scripts', postgresql.JSONB(), nullable=True, default={}),
        sa.Column('references', postgresql.JSONB(), nullable=True, default={}),
        sa.Column('assets', postgresql.JSONB(), nullable=True, default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('activation_count', sa.Integer(), nullable=False, default=0),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('tags_array', postgresql.ARRAY(sa.Text()), nullable=True, default=[]),
        sa.PrimaryKeyConstraint('id'),
        schema='execution'
    )

    # Indexes for skill
    op.create_index('ix_execution_skill_source_id', 'skill', ['source_id'], schema='execution')
    op.create_index('ix_execution_skill_status', 'skill', ['status'], schema='execution')
    op.create_index('ix_execution_skill_trust_state', 'skill', ['trust_state'], schema='execution')
    op.create_index('ix_execution_skill_security_status', 'skill', ['security_status'], schema='execution')
    op.create_index('ix_execution_skill_content_hash', 'skill', ['content_hash'], schema='execution')
    op.create_index('ix_execution_skill_name', 'skill', ['name'], schema='execution')

    # skill_source table
    op.create_table(
        'skill_source',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('source_type', sa.Text(), nullable=False),
        sa.Column('location', sa.Text(), nullable=False),
        sa.Column('priority', sa.Integer(), nullable=False, default=0),
        sa.Column('enabled', sa.Boolean(), nullable=False, default=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=True, default={}),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        schema='execution'
    )

    op.create_index('ix_execution_skill_source_type', 'skill_source', ['source_type'], schema='execution')
    op.create_index('ix_execution_skill_source_enabled', 'skill_source', ['enabled'], schema='execution')

    # skill_security_record table
    op.create_table(
        'skill_security_record',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('skill_id', sa.Text(), nullable=False),
        sa.Column('scan_result', sa.Text(), nullable=False),
        sa.Column('findings', postgresql.JSONB(), nullable=True, default=[]),
        sa.Column('scanned_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('scanner_version', sa.Text(), nullable=False, default='1.0.0'),
        sa.Column('scan_duration_ms', sa.Float(), nullable=False, default=0.0),
        sa.ForeignKeyConstraint(['skill_id'], ['execution.skill.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='execution'
    )

    op.create_index('ix_execution_skill_security_record_skill_id', 'skill_security_record', ['skill_id'], schema='execution')
    op.create_index('ix_execution_skill_security_record_scan_result', 'skill_security_record', ['scan_result'], schema='execution')

    # capability_implementation table
    op.create_table(
        'capability_implementation',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('capability_id', sa.Text(), nullable=False),
        sa.Column('source', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('version', sa.Text(), nullable=False),
        sa.Column('runtime_type', sa.Text(), nullable=False),
        sa.Column('runtime_config', postgresql.JSONB(), nullable=True, default={}),
        sa.Column('tool_ids', postgresql.JSONB(), nullable=True, default=[]),
        sa.Column('skill_ids', postgresql.JSONB(), nullable=True, default=[]),
        sa.Column('required_capabilities', postgresql.JSONB(), nullable=True, default=[]),
        sa.Column('required_environment', postgresql.JSONB(), nullable=True, default={}),
        sa.Column('resource_requirements', postgresql.JSONB(), nullable=True, default={}),
        sa.Column('compatibility', postgresql.JSONB(), nullable=True, default={}),
        sa.Column('tags', postgresql.JSONB(), nullable=True, default=[]),
        sa.Column('status', sa.Text(), nullable=False, default='registered'),
        sa.Column('security_status', sa.Text(), nullable=False, default='approved'),
        sa.Column('experience_score', sa.Float(), nullable=False, default=0.5),
        sa.Column('reliability_score', sa.Float(), nullable=False, default=0.5),
        sa.Column('avg_latency_ms', sa.Float(), nullable=False, default=0.0),
        sa.Column('avg_cost', sa.Float(), nullable=False, default=0.0),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('usage_count', sa.Integer(), nullable=False, default=0),
        sa.Column('success_count', sa.Integer(), nullable=False, default=0),
        sa.Column('failure_count', sa.Integer(), nullable=False, default=0),
        sa.Column('error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        schema='execution'
    )

    op.create_index('ix_execution_capability_implementation_capability_id', 'capability_implementation', ['capability_id'], schema='execution')
    op.create_index('ix_execution_capability_implementation_source', 'capability_implementation', ['source'], schema='execution')
    op.create_index('ix_execution_capability_implementation_status', 'capability_implementation', ['status'], schema='execution')
    op.create_index('ix_execution_capability_implementation_runtime_type', 'capability_implementation', ['runtime_type'], schema='execution')

    # agent_message table
    op.create_table(
        'agent_message',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('message_id', sa.Text(), nullable=False, unique=True),
        sa.Column('sender_agent_id', sa.Text(), nullable=False),
        sa.Column('recipient_agent_id', sa.Text(), nullable=True),
        sa.Column('mission_id', sa.Text(), nullable=False),
        sa.Column('task_id', sa.Text(), nullable=True),
        sa.Column('correlation_id', sa.Text(), nullable=True),
        sa.Column('message_type', sa.Text(), nullable=False),
        sa.Column('priority', sa.Text(), nullable=False, default='normal'),
        sa.Column('payload', postgresql.JSONB(), nullable=True, default={}),
        sa.Column('status', sa.Text(), nullable=False, default='sent'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retry_count', sa.Integer(), nullable=False, default=0),
        sa.Column('max_retries', sa.Integer(), nullable=False, default=3),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=True, default={}),
        sa.ForeignKeyConstraint(['sender_agent_id'], ['execution.agent_instance.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['recipient_agent_id'], ['execution.agent_instance.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['mission_id'], ['execution.mission.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['task_id'], ['execution.autonomous_task.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='execution'
    )

    op.create_index('ix_execution_agent_message_mission_id', 'agent_message', ['mission_id'], schema='execution')
    op.create_index('ix_execution_agent_message_sender_agent_id', 'agent_message', ['sender_agent_id'], schema='execution')
    op.create_index('ix_execution_agent_message_recipient_agent_id', 'agent_message', ['recipient_agent_id'], schema='execution')
    op.create_index('ix_execution_agent_message_task_id', 'agent_message', ['task_id'], schema='execution')
    op.create_index('ix_execution_agent_message_correlation_id', 'agent_message', ['correlation_id'], schema='execution')
    op.create_index('ix_execution_agent_message_status', 'agent_message', ['status'], schema='execution')
    op.create_index('ix_execution_agent_message_created_at', 'agent_message', ['created_at'], schema='execution')

    # runtime_profile table
    op.create_table(
        'runtime_profile',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('runtime_type', sa.Text(), nullable=False),
        sa.Column('config', postgresql.JSONB(), nullable=True, default={}),
        sa.Column('capabilities', postgresql.JSONB(), nullable=True, default=[]),
        sa.Column('resource_limits', postgresql.JSONB(), nullable=True, default={}),
        sa.Column('enabled', sa.Boolean(), nullable=False, default=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint('id'),
        schema='execution'
    )

    op.create_index('ix_execution_runtime_profile_runtime_type', 'runtime_profile', ['runtime_type'], schema='execution')
    op.create_index('ix_execution_runtime_profile_enabled', 'runtime_profile', ['enabled'], schema='execution')

    # wait_condition table
    op.create_table(
        'wait_condition',
        sa.Column('id', sa.Text(), nullable=False),
        sa.Column('task_id', sa.Text(), nullable=False),
        sa.Column('mission_id', sa.Text(), nullable=False),
        sa.Column('condition_type', sa.Text(), nullable=False),
        sa.Column('condition_data', postgresql.JSONB(), nullable=True, default={}),
        sa.Column('status', sa.Text(), nullable=False, default='pending'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('satisfied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(), nullable=True, default={}),
        sa.ForeignKeyConstraint(['task_id'], ['execution.autonomous_task.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['mission_id'], ['execution.mission.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        schema='execution'
    )

    op.create_index('ix_execution_wait_condition_task_id', 'wait_condition', ['task_id'], schema='execution')
    op.create_index('ix_execution_wait_condition_mission_id', 'wait_condition', ['mission_id'], schema='execution')
    op.create_index('ix_execution_wait_condition_status', 'wait_condition', ['status'], schema='execution')
    op.create_index('ix_execution_wait_condition_condition_type', 'wait_condition', ['condition_type'], schema='execution')


def downgrade() -> None:
    # Drop tables in reverse order
    op.drop_table('wait_condition', schema='execution')
    op.drop_table('runtime_profile', schema='execution')
    op.drop_table('agent_message', schema='execution')
    op.drop_table('capability_implementation', schema='execution')
    op.drop_table('skill_security_record', schema='execution')
    op.drop_table('skill_source', schema='execution')
    op.drop_table('skill', schema='execution')