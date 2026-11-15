"""Transactional pipeline events, operation receipts and durable stage retries.
Revision ID: 0011
Revises: 0010

Explicit DDL (not live ORM models) so this revision is stable when models evolve.
"""
from alembic import op
import sqlalchemy as sa
revision='0011';down_revision='0010';branch_labels=None;depends_on=None


def _has(bind,table,schema):return sa.inspect(bind).has_table(table,schema=schema)


def upgrade():
 bind=op.get_bind()
 columns={c['name'] for c in sa.inspect(bind).get_columns('pipeline_stages',schema='operations')}
 for column in [sa.Column('next_retry_at',sa.DateTime(timezone=True)),sa.Column('operation_key',sa.String(64))]:
  if column.name not in columns:op.add_column('pipeline_stages',column,schema='operations')
 if not _has(bind,'pipeline_events','operations'):
  op.create_table('pipeline_events',
   sa.Column('id',sa.String(36),primary_key=True),sa.Column('event_key',sa.String(64),nullable=False),
   sa.Column('fixture_id',sa.String(36)),sa.Column('kind',sa.String(80),nullable=False),sa.Column('payload',sa.JSON()),
   sa.Column('status',sa.String(24),nullable=False),sa.Column('attempts',sa.Integer(),nullable=False),
   sa.Column('available_at',sa.DateTime(timezone=True)),sa.Column('lease_until',sa.DateTime(timezone=True)),
   sa.Column('created_at',sa.DateTime(timezone=True)),sa.Column('completed_at',sa.DateTime(timezone=True)),
   sa.Column('error_code',sa.String(100)),sa.UniqueConstraint('event_key'),schema='operations')
  op.create_index('ix_pipeline_events_due','pipeline_events',['status','available_at'],schema='operations')
 if not _has(bind,'stage_records','operations'):
  op.create_table('stage_records',
   sa.Column('id',sa.String(36),primary_key=True),
   sa.Column('run_id',sa.String(36),sa.ForeignKey('operations.pipeline_runs.id'),nullable=False),
   sa.Column('fixture_id',sa.String(36),sa.ForeignKey('fixtures.fixtures.id'),nullable=False),
   sa.Column('stage_key',sa.String(30),nullable=False),sa.Column('kind',sa.String(50),nullable=False),
   sa.Column('operation_key',sa.String(64),nullable=False),sa.Column('status',sa.String(30),nullable=False),
   sa.Column('evidence_ids',sa.JSON()),sa.Column('details',sa.JSON()),sa.Column('created_at',sa.DateTime(timezone=True)),
   sa.UniqueConstraint('operation_key'),schema='operations')
  op.create_index('ix_stage_records_fixture','stage_records',['fixture_id','kind','created_at'],schema='operations')
 if not _has(bind,'odds_evidence','markets'):
  op.create_table('odds_evidence',
   sa.Column('odds_id',sa.String(36),sa.ForeignKey('markets.odds_snapshots.id'),primary_key=True),
   sa.Column('observation_id',sa.String(36),sa.ForeignKey('sources.observations.id'),nullable=False),
   sa.Column('source_id',sa.String(36),sa.ForeignKey('sources.providers.id'),nullable=False),schema='markets')


def downgrade():
 bind=op.get_bind()
 for table,schema in (('odds_evidence','markets'),('stage_records','operations'),('pipeline_events','operations')):
  if _has(bind,table,schema):op.drop_table(table,schema=schema)
 op.drop_column('pipeline_stages','operation_key',schema='operations')
 op.drop_column('pipeline_stages','next_retry_at',schema='operations')
