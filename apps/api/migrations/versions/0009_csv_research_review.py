"""Pending review and provenance for authorized CSV/JSON research imports.
Revision ID: 0009
Revises: 0008
"""
from alembic import op
import sqlalchemy as sa
revision='0009';down_revision='0008';branch_labels=None;depends_on=None

def upgrade():
 bind=op.get_bind()
 columns={c['name'] for c in sa.inspect(bind).get_columns('standings_snapshots',schema='research')}
 additions=[sa.Column('review_status',sa.String(24),nullable=False,server_default='VERIFIED'),
            sa.Column('reviewed_by',sa.String(200),nullable=True),
            sa.Column('imported_at',sa.DateTime(timezone=True),nullable=False,server_default=sa.func.now()),
            sa.Column('provenance',sa.JSON(),nullable=False,server_default=sa.text("'{}'"))]
 for column in additions:
  if column.name not in columns:op.add_column('standings_snapshots',column,schema='research')
 op.alter_column('standings_snapshots','verified_at',nullable=True,schema='research')

def downgrade():
 # Preserve pending imports on rollback. NULL verification prevents them being served by 0008 readers.
 if op.get_bind().scalar(sa.text('SELECT count(*) FROM research.standings_snapshots WHERE verified_at IS NULL')):
  raise RuntimeError('Resolve pending snapshots through an explicit archival/review workflow before downgrading; pending evidence is preserved')
 op.alter_column('standings_snapshots','verified_at',nullable=False,schema='research')
 for name in ('provenance','imported_at','reviewed_by','review_status'):
  op.drop_column('standings_snapshots',name,schema='research')
