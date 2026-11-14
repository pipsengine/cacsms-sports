from alembic import op
import sqlalchemy as sa
revision='0005';down_revision='0004';branch_labels=None;depends_on=None
def upgrade():
 op.create_table('result_evidence',sa.Column('id',sa.String(36),primary_key=True),sa.Column('result_id',sa.String(36),sa.ForeignKey('results.official_results.id'),nullable=False),sa.Column('source_id',sa.String(36),sa.ForeignKey('sources.providers.id'),nullable=False),sa.Column('observation_id',sa.String(36),sa.ForeignKey('sources.observations.id'),nullable=False),sa.UniqueConstraint('result_id','observation_id',name='result_evidence_unique'),schema='results')
def downgrade():
 op.drop_table('result_evidence',schema='results')
