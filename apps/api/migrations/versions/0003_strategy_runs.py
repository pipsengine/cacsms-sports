"""Strategy run audit persistence."""
from alembic import op
import sqlalchemy as sa
revision='0003_strategy_runs'
down_revision='0002'
branch_labels=None
depends_on=None

def upgrade():
 op.create_table('runs',sa.Column('id',sa.String(36),primary_key=True),sa.Column('programme_key',sa.String(50),nullable=False),sa.Column('idempotency_key',sa.String(128),nullable=False),sa.Column('status',sa.String(30),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),sa.Column('result',sa.JSON(),nullable=False),sa.UniqueConstraint('programme_key','idempotency_key',name='strategy_run_unique'),schema='strategies')
 op.create_index('ix_strategies_runs_programme_key','runs',['programme_key'],schema='strategies')
def downgrade():
 op.drop_index('ix_strategies_runs_programme_key',table_name='runs',schema='strategies')
 op.drop_table('runs',schema='strategies')
