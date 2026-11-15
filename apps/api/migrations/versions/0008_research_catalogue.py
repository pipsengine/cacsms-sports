"""Season-aware research catalogue and provenance-backed standings.
Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa
from app.db import models as m
revision='0008';down_revision='0007';branch_labels=None;depends_on=None

def upgrade():
 bind=op.get_bind()
 m.CompetitionSeason.__table__.create(bind,checkfirst=True)
 # The initial migration uses current metadata; support both fresh and existing installs.
 if 'season_id' not in {c['name'] for c in sa.inspect(bind).get_columns('fixtures',schema='fixtures')}:
  op.add_column('fixtures',sa.Column('season_id',sa.String(36),nullable=True),schema='fixtures')
  op.create_foreign_key('fk_fixtures_season_id_competition_seasons','fixtures','competition_seasons',['season_id'],['id'],source_schema='fixtures',referent_schema='sports')
  op.create_index('ix_fixtures_fixtures_season_id','fixtures',['season_id'],schema='fixtures')
 m.StandingsSnapshot.__table__.create(bind,checkfirst=True)

def downgrade():
 m.StandingsSnapshot.__table__.drop(op.get_bind(),checkfirst=True)
 op.drop_index('ix_fixtures_fixtures_season_id',table_name='fixtures',schema='fixtures')
 op.drop_constraint('fk_fixtures_season_id_competition_seasons','fixtures',schema='fixtures',type_='foreignkey')
 op.drop_column('fixtures','season_id',schema='fixtures')
 m.CompetitionSeason.__table__.drop(op.get_bind(),checkfirst=True)
