"""Append-only odds quality evidence over existing canonical snapshots.

Revision ID: 0016
Revises: 0015
"""
from alembic import op
import sqlalchemy as sa

revision='0016'
down_revision='0015'
branch_labels=None
depends_on=None


def upgrade():
    op.create_table('odds_quality_assessments',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('odds_id',sa.String(36),sa.ForeignKey('markets.odds_snapshots.id'),nullable=False),
        sa.Column('observation_id',sa.String(36),sa.ForeignKey('sources.observations.id')),
        sa.Column('assessed_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('classification',sa.String(24),nullable=False),
        sa.Column('eligible',sa.Boolean(),nullable=False),
        sa.Column('reasons',sa.JSON(),nullable=False),
        sa.Column('policy_version',sa.String(30),nullable=False),schema='markets')
    op.create_index('ix_odds_quality_quote_time','odds_quality_assessments',['odds_id','assessed_at'],schema='markets')
    op.execute("""CREATE FUNCTION markets.preserve_odds_quality() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN RAISE EXCEPTION 'Odds quality evidence is append-only'; END $$""")
    op.execute('CREATE TRIGGER odds_quality_immutable BEFORE UPDATE OR DELETE ON markets.odds_quality_assessments FOR EACH ROW EXECUTE FUNCTION markets.preserve_odds_quality()')


def downgrade():
    op.drop_table('odds_quality_assessments',schema='markets')
    op.execute('DROP FUNCTION markets.preserve_odds_quality()')
