"""Fixture matchday (provider round number) for research headers.
Revision ID: 0013
Revises: 0012
"""
from alembic import op
import sqlalchemy as sa
revision='0013';down_revision='0012';branch_labels=None;depends_on=None


def upgrade():
 columns={c['name'] for c in sa.inspect(op.get_bind()).get_columns('fixtures',schema='fixtures')}
 if 'matchday' not in columns:op.add_column('fixtures',sa.Column('matchday',sa.Integer()),schema='fixtures')


def downgrade():
 op.drop_column('fixtures','matchday',schema='fixtures')
