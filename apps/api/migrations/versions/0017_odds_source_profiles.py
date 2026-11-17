"""Configurable source capabilities, separate from authorization.

Revision ID: 0017
Revises: 0016
"""
from alembic import op
from app.db.base import Base
from app.db import models

revision='0017'
down_revision='0016'
branch_labels=None
depends_on=None


def upgrade():
    Base.metadata.tables['sources.odds_sources'].create(op.get_bind(), checkfirst=True)
    # Preserve conflicting prices for quarantine; reject exact duplicates only.
    op.execute('CREATE UNIQUE INDEX IF NOT EXISTS odds_price_identity ON markets.odds_snapshots (fixture_id,bookmaker,market_key,outcome_key,observed_at,decimal_odds)')


def downgrade():
    op.execute('ALTER TABLE markets.odds_snapshots DROP CONSTRAINT IF EXISTS odds_price_identity')
    op.execute('DROP INDEX IF EXISTS markets.odds_price_identity')
    Base.metadata.tables['sources.odds_sources'].drop(op.get_bind(), checkfirst=True)
