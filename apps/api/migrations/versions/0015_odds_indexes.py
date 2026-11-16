"""Indexes for odds access paths (per-fixture lookups, market grouping, evidence joins).
Revision ID: 0015
Revises: 0014

The closing-odds archive makes markets.odds_snapshots large; only primary keys existed before.
"""
from alembic import op
revision='0015';down_revision='0014';branch_labels=None;depends_on=None
INDEXES=[('ix_odds_fixture_observed','odds_snapshots','fixture_id, observed_at'),('ix_odds_market_outcome','odds_snapshots','market_key, outcome_key'),
         ('ix_odds_bookmaker_market','odds_snapshots','bookmaker, market_key'),('ix_odds_evidence_observation','odds_evidence','observation_id')]


def upgrade():
 for name,table,columns in INDEXES:op.execute(f'CREATE INDEX IF NOT EXISTS {name} ON markets.{table} ({columns})')


def downgrade():
 for name,_,_ in INDEXES:op.execute(f'DROP INDEX IF EXISTS markets.{name}')
