"""Durable twelve-stage workflow ledger.
Revision ID: 0007
Revises: 0006
"""
from alembic import op
import sqlalchemy as sa
revision='0007';down_revision='0006';branch_labels=None;depends_on=None

def upgrade():
 op.create_table('pipeline_runs',sa.Column('id',sa.String(36),primary_key=True),sa.Column('idempotency_key',sa.String(128),nullable=False),sa.Column('fixture_id',sa.String(36)),sa.Column('status',sa.String(30),nullable=False),sa.Column('mode',sa.String(20),nullable=False),sa.Column('context',sa.JSON(),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True)),sa.Column('updated_at',sa.DateTime(timezone=True)),sa.UniqueConstraint('idempotency_key',name='uq_pipeline_idempotency'),schema='operations')
 op.create_table('pipeline_stages',sa.Column('id',sa.String(36),primary_key=True),sa.Column('run_id',sa.String(36),sa.ForeignKey('operations.pipeline_runs.id'),nullable=False),sa.Column('position',sa.Integer(),nullable=False),sa.Column('stage_key',sa.String(30),nullable=False),sa.Column('status',sa.String(30),nullable=False),sa.Column('input_payload',sa.JSON(),nullable=False),sa.Column('output_payload',sa.JSON(),nullable=False),sa.Column('evidence_ids',sa.JSON(),nullable=False),sa.Column('error',sa.Text()),sa.Column('retry_count',sa.Integer(),nullable=False),sa.Column('started_at',sa.DateTime(timezone=True)),sa.Column('finished_at',sa.DateTime(timezone=True)),sa.Column('duration_ms',sa.Integer()),sa.UniqueConstraint('run_id','position',name='uq_pipeline_stage_order'),schema='operations')
 op.create_index('ix_pipeline_stages_run_id','pipeline_stages',['run_id'],schema='operations')
def downgrade():
 op.drop_index('ix_pipeline_stages_run_id',table_name='pipeline_stages',schema='operations')
 op.drop_table('pipeline_stages',schema='operations')
 op.drop_table('pipeline_runs',schema='operations')
