"""Transactional pipeline events, operation receipts and durable stage retries.
Revision ID: 0011
Revises: 0010
"""
from alembic import op
import sqlalchemy as sa
from app.db import models as m
revision='0011';down_revision='0010';branch_labels=None;depends_on=None

def upgrade():
 bind=op.get_bind()
 columns={c['name'] for c in sa.inspect(bind).get_columns('pipeline_stages',schema='operations')}
 for column in [sa.Column('next_retry_at',sa.DateTime(timezone=True)),sa.Column('operation_key',sa.String(64))]:
  if column.name not in columns:op.add_column('pipeline_stages',column,schema='operations')
 m.PipelineEvent.__table__.create(bind,checkfirst=True)
 m.StageRecord.__table__.create(bind,checkfirst=True)

def downgrade():
 m.StageRecord.__table__.drop(op.get_bind(),checkfirst=True)
 m.PipelineEvent.__table__.drop(op.get_bind(),checkfirst=True)
 op.drop_column('pipeline_stages','operation_key',schema='operations')
 op.drop_column('pipeline_stages','next_retry_at',schema='operations')
