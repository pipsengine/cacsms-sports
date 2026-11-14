"""Persistent paper betslips and verification trail."""
from alembic import op
import sqlalchemy as sa
revision='0004';down_revision='0003_strategy_runs';branch_labels=None;depends_on=None

def upgrade():
 op.create_table('betslips',sa.Column('id',sa.String(36),primary_key=True),sa.Column('ticket_id',sa.String(36),sa.ForeignKey('tickets.tickets.id'),nullable=False),sa.Column('bookmaker',sa.String(60)),sa.Column('status',sa.String(32)),sa.Column('selections',sa.JSON(),nullable=False),sa.Column('combined_odds',sa.Numeric(16,5),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True)),sa.UniqueConstraint('ticket_id',name='betslip_ticket_unique'),schema='tickets')
 op.create_table('ticket_verifications',sa.Column('id',sa.String(36),primary_key=True),sa.Column('ticket_id',sa.String(36),sa.ForeignKey('tickets.tickets.id'),nullable=False),sa.Column('status',sa.String(30),nullable=False),sa.Column('reason_codes',sa.JSON()),sa.Column('evidence',sa.JSON()),sa.Column('verified_at',sa.DateTime(timezone=True)),schema='tickets')
 op.create_index('ix_ticket_verifications_ticket_id','ticket_verifications',['ticket_id'],schema='tickets')
 # Ensure ticket preparation has valid strategy programme references.
 import uuid,json
 for key in ('accumulator','singles','jackpot','draws','rollover'):
  op.execute(sa.text("INSERT INTO strategies.programmes (id,key,configuration) VALUES (:id,:key,CAST(:config AS JSON)) ON CONFLICT (key) DO NOTHING").bindparams(id=str(uuid.uuid4()),key=key,config=json.dumps({'execution_mode':'PAPER'})))

def downgrade():
 op.drop_index('ix_ticket_verifications_ticket_id',table_name='ticket_verifications',schema='tickets')
 op.drop_table('ticket_verifications',schema='tickets')
 op.drop_table('betslips',schema='tickets')
