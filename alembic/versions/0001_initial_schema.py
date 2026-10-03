"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-10-03 15:30:21.289216
"""
from alembic import op
import sqlalchemy as sa


revision = '0001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('robots',
    sa.Column('robot_id', sa.String(length=50), nullable=False),
    sa.PrimaryKeyConstraint('robot_id')
    )
    # Reference data: the robots the company operates (see seed/README.md). New robots = a new migration.
    robots = sa.table("robots", sa.column("robot_id", sa.String))
    op.bulk_insert(robots, [{"robot_id": r} for r in ("arm-01", "arm-02", "arm-03", "mobile-01", "humanoid-01")])
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('organisation', sa.String(length=200), nullable=True),
    sa.Column('password_hash', sa.String(length=255), nullable=False),
    sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("role IN ('client','operator','admin')", name='ck_users_role'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email')
    )
    op.create_table('episodes',
    sa.Column('id', sa.BigInteger(), nullable=False),
    sa.Column('episode_id', sa.String(length=50), nullable=False),
    sa.Column('robot_id', sa.String(length=50), nullable=False),
    sa.Column('task_name', sa.String(length=200), nullable=False),
    sa.Column('recorded_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('duration_seconds', sa.Integer(), nullable=False),
    sa.Column('operator_name', sa.String(length=200), nullable=True),
    sa.Column('quality', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("quality IN ('good','usable','bad')", name='ck_episodes_quality'),
    sa.CheckConstraint('duration_seconds > 0', name='ck_episodes_duration_positive'),
    sa.ForeignKeyConstraint(['robot_id'], ['robots.robot_id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('episode_id')
    )
    op.create_index('ix_episodes_recorded_at', 'episodes', ['recorded_at'], unique=False)
    op.create_index('ix_episodes_robot_recorded', 'episodes', ['robot_id', 'recorded_at'], unique=False)
    op.create_index('ix_episodes_task_quality', 'episodes', ['task_name', 'quality'], unique=False)
    op.create_table('requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('client_id', sa.Integer(), nullable=False),
    sa.Column('task_name', sa.String(length=200), nullable=False),
    sa.Column('episodes_requested', sa.Integer(), nullable=False),
    sa.Column('deadline', sa.Date(), nullable=False),
    sa.Column('notes', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='submitted', nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.CheckConstraint("status IN ('submitted','in_progress','delivered','accepted','rejected')", name='ck_requests_status'),
    sa.CheckConstraint('episodes_requested > 0', name='ck_requests_count_positive'),
    sa.ForeignKeyConstraint(['client_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_requests_client', 'requests', ['client_id'], unique=False)
    op.create_index('ix_requests_created_at', 'requests', ['created_at'], unique=False)
    op.create_index('ix_requests_status', 'requests', ['status'], unique=False)
    op.create_table('assignments',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('episode_pk', sa.BigInteger(), nullable=False),
    sa.Column('assigned_by', sa.Integer(), nullable=False),
    sa.Column('assigned_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['assigned_by'], ['users.id'], ),
    sa.ForeignKeyConstraint(['episode_pk'], ['episodes.id'], ),
    sa.ForeignKeyConstraint(['request_id'], ['requests.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('episode_pk', name='uq_assignments_episode')
    )
    op.create_index('ix_assignments_request', 'assignments', ['request_id'], unique=False)
    op.create_table('request_status_history',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('request_id', sa.Integer(), nullable=False),
    sa.Column('from_status', sa.String(length=20), nullable=True),
    sa.Column('to_status', sa.String(length=20), nullable=False),
    sa.Column('actor_id', sa.Integer(), nullable=False),
    sa.Column('comment', sa.Text(), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], ),
    sa.ForeignKeyConstraint(['request_id'], ['requests.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_history_request_at', 'request_status_history', ['request_id', 'at'], unique=False)
    op.create_index('ix_history_to_status', 'request_status_history', ['to_status', 'request_id'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_history_to_status', table_name='request_status_history')
    op.drop_index('ix_history_request_at', table_name='request_status_history')
    op.drop_table('request_status_history')
    op.drop_index('ix_assignments_request', table_name='assignments')
    op.drop_table('assignments')
    op.drop_index('ix_requests_status', table_name='requests')
    op.drop_index('ix_requests_created_at', table_name='requests')
    op.drop_index('ix_requests_client', table_name='requests')
    op.drop_table('requests')
    op.drop_index('ix_episodes_task_quality', table_name='episodes')
    op.drop_index('ix_episodes_robot_recorded', table_name='episodes')
    op.drop_index('ix_episodes_recorded_at', table_name='episodes')
    op.drop_table('episodes')
    op.drop_table('users')
    op.drop_table('robots')
