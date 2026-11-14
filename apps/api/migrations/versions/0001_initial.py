"""Initial PostgreSQL domain schema
Revision ID: 0001
Revises:
"""
from alembic import op
from app.db.base import Base
from app.db import models
revision='0001';down_revision=None;branch_labels=None;depends_on=None
schemas=['core','sports','fixtures','sources','research','features','models','predictions','markets','qualification','strategies','tickets','results','operations','audit']
def upgrade():
 for schema in schemas:op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
 Base.metadata.create_all(bind=op.get_bind(),tables=[t for t in Base.metadata.sorted_tables if t.fullname not in {'operations.acquisition_jobs','strategies.runs','tickets.betslips','tickets.ticket_verifications','results.result_evidence','operations.browser_captures','models.governance_snapshots'}])
def downgrade():
 Base.metadata.drop_all(bind=op.get_bind())
 for schema in reversed(schemas):op.execute(f'DROP SCHEMA IF EXISTS "{schema}"')
