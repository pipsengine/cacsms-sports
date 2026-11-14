from alembic import op
import sqlalchemy as sa
revision='0006';down_revision='0005';branch_labels=None;depends_on=None
def upgrade():
 op.create_table('browser_captures',sa.Column('id',sa.String(36),primary_key=True),sa.Column('fixture_id',sa.String(36),sa.ForeignKey('fixtures.fixtures.id'),nullable=False),sa.Column('source_id',sa.String(36),sa.ForeignKey('sources.providers.id'),nullable=False),sa.Column('url',sa.Text(),nullable=False),sa.Column('status',sa.String(32)),sa.Column('vision_status',sa.String(48)),sa.Column('evidence_hash',sa.String(64)),sa.Column('error',sa.Text()),sa.Column('created_at',sa.DateTime(timezone=True)),schema='operations')
 op.create_table('governance_snapshots',sa.Column('id',sa.String(36),primary_key=True),sa.Column('model_id',sa.String(36),sa.ForeignKey('models.versions.id'),nullable=False),sa.Column('status',sa.String(32),nullable=False),sa.Column('reasons',sa.JSON()),sa.Column('reference',sa.JSON()),sa.Column('recent',sa.JSON()),sa.Column('created_at',sa.DateTime(timezone=True)),schema='models')
 op.create_index('ix_governance_model_id','governance_snapshots',['model_id'],schema='models')
def downgrade():
 op.drop_index('ix_governance_model_id',table_name='governance_snapshots',schema='models')
 op.drop_table('governance_snapshots',schema='models')
 op.drop_table('browser_captures',schema='operations')
