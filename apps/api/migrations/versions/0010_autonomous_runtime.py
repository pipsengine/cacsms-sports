"""Persistent autonomous PAPER controller heartbeat and concurrency lease.
Revision ID: 0010
Revises: 0009
"""
from alembic import op
from app.db import models as m
revision='0010';down_revision='0009';branch_labels=None;depends_on=None

def upgrade():
 m.AutonomousRuntime.__table__.create(op.get_bind(),checkfirst=True)
 m.ProviderSyncState.__table__.create(op.get_bind(),checkfirst=True)

def downgrade():
 m.ProviderSyncState.__table__.drop(op.get_bind(),checkfirst=True)
 m.AutonomousRuntime.__table__.drop(op.get_bind(),checkfirst=True)
