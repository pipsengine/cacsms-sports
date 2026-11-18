"""Durable competition discovery, fixture candidates, leases and source identity.
Revision ID: 0018
Revises: 0017
"""
from alembic import op
from app.db.base import Base
from app.db import models
revision='0018';down_revision='0017';branch_labels=None;depends_on=None
TABLES=('sources.discovery_competitions','operations.fixture_discovery_jobs','sources.fixture_candidates','sources.fixture_source_mappings')

def upgrade():
 for name in TABLES:Base.metadata.tables[name].create(op.get_bind(),checkfirst=True)

def downgrade():
 for name in reversed(TABLES):Base.metadata.tables[name].drop(op.get_bind(),checkfirst=True)
