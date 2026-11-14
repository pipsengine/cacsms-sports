"""Durable acquisition queue
Revision ID: 0002
Revises: 0001
"""
from alembic import op
from app.db import models as m
revision='0002';down_revision='0001';branch_labels=None;depends_on=None
def upgrade():
 m.AcquisitionJob.__table__.create(bind=op.get_bind(),checkfirst=True)
def downgrade():
 m.AcquisitionJob.__table__.drop(bind=op.get_bind(),checkfirst=True)
