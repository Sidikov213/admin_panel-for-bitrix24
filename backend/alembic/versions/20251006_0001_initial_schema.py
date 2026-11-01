"""Frozen initial schema; later revisions own their additions."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20251006_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Immutable base tables.
    op.create_table('crm_activities',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('bitrix_id', sa.BigInteger(), nullable=False),
    sa.Column('type_id', sa.Integer(), nullable=True),
    sa.Column('subject', sa.String(length=512), nullable=True),
    sa.Column('responsible_id', sa.Integer(), nullable=True),
    sa.Column('owner_type_id', sa.Integer(), nullable=True),
    sa.Column('owner_id', sa.BigInteger(), nullable=True),
    sa.Column('created', sa.DateTime(timezone=True), nullable=True),
    sa.Column('deadline', sa.DateTime(timezone=True), nullable=True),
    sa.Column('completed', sa.Boolean(), nullable=False),
    sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_crm_activities_bitrix_id'), 'crm_activities', ['bitrix_id'], unique=True)
    op.create_index(op.f('ix_crm_activities_completed'), 'crm_activities', ['completed'], unique=False)
    op.create_index(op.f('ix_crm_activities_deadline'), 'crm_activities', ['deadline'], unique=False)
    op.create_index('ix_crm_activities_owner_completed', 'crm_activities', ['owner_id', 'completed'], unique=False)
    op.create_index(op.f('ix_crm_activities_owner_id'), 'crm_activities', ['owner_id'], unique=False)
    op.create_table('crm_managers',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('bitrix_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('last_name', sa.String(length=255), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('raw', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_crm_managers_bitrix_id'), 'crm_managers', ['bitrix_id'], unique=True)
    op.create_table('crm_pipelines',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('bitrix_id', sa.BigInteger(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('sort', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_crm_pipelines_bitrix_id'), 'crm_pipelines', ['bitrix_id'], unique=True)
    op.create_table('login_attempts',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('ip', sa.String(length=45), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('attempted_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_login_attempts_attempted_at'), 'login_attempts', ['attempted_at'], unique=False)
    op.create_index('ix_login_attempts_ip_email_at', 'login_attempts', ['ip', 'email', 'attempted_at'], unique=False)
    op.create_table('sync_runs',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('sync_type', sa.Enum('dictionaries', 'deals', 'activities', 'full_reconcile', name='sync_type'), nullable=False),
    sa.Column('status', sa.Enum('running', 'success', 'failed', name='sync_status'), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('items_processed', sa.Integer(), nullable=False),
    sa.Column('errors_count', sa.Integer(), nullable=False),
    sa.Column('error_message', sa.Text(), nullable=True),
    sa.Column('cursor_info', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sync_runs_sync_type'), 'sync_runs', ['sync_type'], unique=False)
    op.create_table('sync_state',
    sa.Column('key', sa.String(length=128), nullable=False),
    sa.Column('value', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('password_hash', sa.Text(), nullable=False),
    sa.Column('role', sa.Enum('admin', 'viewer', name='user_role'), nullable=False),
    sa.Column('is_active', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)
    op.create_table('analytics_daily',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('date', sa.Date(), nullable=False),
    sa.Column('pipeline_id', sa.Integer(), nullable=True),
    sa.Column('manager_id', sa.Integer(), nullable=True),
    sa.Column('metrics', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['manager_id'], ['crm_managers.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['pipeline_id'], ['crm_pipelines.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('date', 'pipeline_id', 'manager_id', name='uq_analytics_daily_dims')
    )
    op.create_index('ix_analytics_daily_date', 'analytics_daily', ['date'], unique=False)
    op.create_table('crm_stages',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('bitrix_id', sa.String(length=64), nullable=False),
    sa.Column('pipeline_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('sort', sa.Integer(), nullable=False),
    sa.Column('semantics', sa.String(length=32), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['pipeline_id'], ['crm_pipelines.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_crm_stages_bitrix_id'), 'crm_stages', ['bitrix_id'], unique=True)
    op.create_index('ix_crm_stages_pipeline_sort', 'crm_stages', ['pipeline_id', 'sort'], unique=False)
    op.create_table('sales_targets',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('manager_id', sa.Integer(), nullable=True),
    sa.Column('period_type', sa.Enum('week', 'month', name='period_type'), nullable=False),
    sa.Column('period_start', sa.Date(), nullable=False),
    sa.Column('period_end', sa.Date(), nullable=False),
    sa.Column('amount', sa.Numeric(precision=18, scale=2), nullable=False),
    sa.Column('currency', sa.String(length=8), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['manager_id'], ['crm_managers.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('manager_id', 'period_type', 'period_start', 'period_end', name='uq_sales_targets_period')
    )
    op.create_table('sessions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('csrf_token', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_sessions_token_hash'), 'sessions', ['token_hash'], unique=True)
    op.create_index('ix_sessions_user_expires', 'sessions', ['user_id', 'expires_at'], unique=False)
    op.create_table('crm_deals',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('bitrix_id', sa.BigInteger(), nullable=False),
    sa.Column('title', sa.String(length=512), nullable=False),
    sa.Column('category_id', sa.Integer(), nullable=True),
    sa.Column('stage_id', sa.Integer(), nullable=True),
    sa.Column('assigned_by_id', sa.Integer(), nullable=True),
    sa.Column('opportunity', sa.Numeric(precision=18, scale=2), nullable=True),
    sa.Column('currency_id', sa.String(length=8), nullable=True),
    sa.Column('date_create', sa.DateTime(timezone=True), nullable=True),
    sa.Column('date_modify', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closedate', sa.DateTime(timezone=True), nullable=True),
    sa.Column('closed', sa.Boolean(), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_observed_activity_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('stage_changed_observed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('has_future_activity', sa.Boolean(), nullable=False),
    sa.Column('open_activities_count', sa.Integer(), nullable=False),
    sa.Column('next_deadline_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('content_hash', sa.String(length=64), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['assigned_by_id'], ['crm_managers.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['stage_id'], ['crm_stages.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_crm_deals_assigned_closed', 'crm_deals', ['assigned_by_id', 'closed'], unique=False)
    op.create_index(op.f('ix_crm_deals_bitrix_id'), 'crm_deals', ['bitrix_id'], unique=True)
    op.create_index(op.f('ix_crm_deals_category_id'), 'crm_deals', ['category_id'], unique=False)
    op.create_index(op.f('ix_crm_deals_closed'), 'crm_deals', ['closed'], unique=False)
    op.create_index(op.f('ix_crm_deals_content_hash'), 'crm_deals', ['content_hash'], unique=False)
    op.create_index('ix_crm_deals_stage_closed', 'crm_deals', ['stage_id', 'closed'], unique=False)
    op.create_table('deal_change_events',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('deal_id', sa.Integer(), nullable=False),
    sa.Column('field_name', sa.String(length=128), nullable=False),
    sa.Column('old_value', sa.Text(), nullable=True),
    sa.Column('new_value', sa.Text(), nullable=True),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('bitrix_event_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['deal_id'], ['crm_deals.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_deal_change_events_deal_observed', 'deal_change_events', ['deal_id', 'observed_at'], unique=False)
    op.create_table('deal_snapshots',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('deal_id', sa.Integer(), nullable=False),
    sa.Column('observed_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.Column('content_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['deal_id'], ['crm_deals.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('deal_id', 'content_hash', name='uq_deal_snapshots_deal_hash')
    )
    op.create_index('ix_deal_snapshots_deal_observed', 'deal_snapshots', ['deal_id', 'observed_at'], unique=False)


def downgrade():
    op.drop_table('deal_snapshots')
    op.drop_table('deal_change_events')
    op.drop_table('crm_deals')
    op.drop_table('sessions')
    op.drop_table('sales_targets')
    op.drop_table('crm_stages')
    op.drop_table('analytics_daily')
    op.drop_table('users')
    op.drop_table('sync_state')
    op.drop_table('sync_runs')
    op.drop_table('login_attempts')
    op.drop_table('crm_pipelines')
    op.drop_table('crm_managers')
    op.drop_table('crm_activities')
    for enum_name in ("user_role", "sync_type", "sync_status", "period_type"):
        sa.Enum(name=enum_name).drop(op.get_bind(), checkfirst=True)
