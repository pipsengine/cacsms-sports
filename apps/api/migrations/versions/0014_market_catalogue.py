"""Market catalogue, per-fixture bookmaker availability, model capabilities and market scans.
Revision ID: 0014
Revises: 0013

Idempotent DDL built from the ORM table definitions (schema 'markets' already exists).
"""
from alembic import op
import sqlalchemy as sa
revision='0014';down_revision='0013';branch_labels=None;depends_on=None
TABLES=('market_categories','market_definitions','market_outcomes','bookmaker_market_mappings','bookmaker_market_availability',
        'market_model_capabilities','market_scan_runs','market_scan_results')


def _tables():
 from app.db.base import Base
 from app.db import models  # noqa: F401 - registers the tables on Base.metadata
 return [Base.metadata.tables['markets.'+name] for name in TABLES]


def upgrade():
 bind=op.get_bind();inspector=sa.inspect(bind)
 for table in _tables():
  if not inspector.has_table(table.name,schema='markets'):table.create(bind)


def downgrade():
 bind=op.get_bind()
 for table in reversed(_tables()):table.drop(bind,checkfirst=True)
