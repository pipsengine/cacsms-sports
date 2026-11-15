"""Stage data contract, immutable stage history, canonical teams/countries and team statistics.
Revision ID: 0012
Revises: 0011

Explicit, idempotent DDL: fresh databases may already have some objects from 0001.
"""
from alembic import op
import sqlalchemy as sa
revision='0012';down_revision='0011';branch_labels=None;depends_on=None


def _inspector():return sa.inspect(op.get_bind())
def _has(table,schema):return _inspector().has_table(table,schema=schema)
def _columns(table,schema):return {c['name'] for c in _inspector().get_columns(table,schema=schema)}


def _add(table,schema,*columns):
 existing=_columns(table,schema)
 for column in columns:
  if column.name not in existing:op.add_column(table,column,schema=schema)


def upgrade():
 if not _has('countries','sports'):
  op.create_table('countries',sa.Column('id',sa.String(36),primary_key=True),sa.Column('name',sa.String(100),nullable=False),
   sa.Column('canonical_key',sa.String(100),nullable=False),sa.Column('code',sa.String(3)),
   sa.UniqueConstraint('canonical_key',name='country_canonical_key'),schema='sports')
 if not _has('teams','sports'):
  op.create_table('teams',sa.Column('id',sa.String(36),primary_key=True),
   sa.Column('sport_id',sa.String(36),sa.ForeignKey('sports.sports.id'),nullable=False),
   sa.Column('country_id',sa.String(36),sa.ForeignKey('sports.countries.id')),
   sa.Column('name',sa.String(200),nullable=False),sa.Column('canonical_key',sa.String(200),nullable=False),
   sa.UniqueConstraint('sport_id','canonical_key',name='team_canonical_key'),schema='sports')
 _add('competitions','sports',sa.Column('country_id',sa.String(36),sa.ForeignKey('sports.countries.id')))
 _add('fixtures','fixtures',sa.Column('home_team_id',sa.String(36),sa.ForeignKey('sports.teams.id')),
      sa.Column('away_team_id',sa.String(36),sa.ForeignKey('sports.teams.id')))
 if not _has('team_statistics','research'):
  op.create_table('team_statistics',sa.Column('id',sa.String(36),primary_key=True),
   sa.Column('team_id',sa.String(36),sa.ForeignKey('sports.teams.id'),nullable=False),
   sa.Column('fixture_id',sa.String(36),sa.ForeignKey('fixtures.fixtures.id'),nullable=False),
   sa.Column('observation_id',sa.String(36),sa.ForeignKey('sources.observations.id'),nullable=False),
   sa.Column('source_id',sa.String(36),sa.ForeignKey('sources.providers.id'),nullable=False),
   sa.Column('section',sa.String(40)),sa.Column('side',sa.String(4)),sa.Column('as_of',sa.DateTime(timezone=True)),
   sa.Column('statistics',sa.JSON()),sa.UniqueConstraint('team_id','observation_id',name='team_statistic_observation'),schema='research')
  op.create_index('ix_research_team_statistics_team_id','team_statistics',['team_id'],schema='research')
  op.create_index('ix_research_team_statistics_fixture_id','team_statistics',['fixture_id'],schema='research')
 _add('forecasts','predictions',sa.Column('details',sa.JSON()))
 _add('pipeline_stages','operations',
      sa.Column('input_version',sa.Integer(),nullable=False,server_default='0'),
      sa.Column('output_version',sa.Integer(),nullable=False,server_default='0'),
      sa.Column('output_reference',sa.String(36)),sa.Column('quality_score',sa.Numeric(6,4)),
      sa.Column('failure_code',sa.String(80)),sa.Column('next_stage',sa.String(30)))
 _add('pipeline_events','operations',sa.Column('content_hash',sa.String(64)))
 if not any(i['column_names']==['content_hash'] for i in _inspector().get_indexes('pipeline_events',schema='operations')):
  op.create_index('ix_operations_pipeline_events_content_hash','pipeline_events',['content_hash'],schema='operations')
 if not _has('pipeline_stage_runs','operations'):
  op.create_table('pipeline_stage_runs',sa.Column('id',sa.String(36),primary_key=True),
   sa.Column('pipeline_run_id',sa.String(36),sa.ForeignKey('operations.pipeline_runs.id'),nullable=False),
   sa.Column('fixture_id',sa.String(36)),sa.Column('stage',sa.String(30),nullable=False),sa.Column('status',sa.String(30),nullable=False),
   sa.Column('attempt',sa.Integer()),sa.Column('input_version',sa.Integer()),sa.Column('output_version',sa.Integer()),
   sa.Column('started_at',sa.DateTime(timezone=True),nullable=False),sa.Column('completed_at',sa.DateTime(timezone=True)),
   sa.Column('duration_ms',sa.Integer()),sa.Column('evidence_ids',sa.JSON()),sa.Column('output_reference',sa.String(36)),
   sa.Column('quality_score',sa.Numeric(6,4)),sa.Column('failure_code',sa.String(80)),sa.Column('failure_reason',sa.Text()),
   sa.Column('next_stage',sa.String(30)),sa.Column('details',sa.JSON()),schema='operations')
  op.create_index('ix_pipeline_stage_runs_run','pipeline_stage_runs',['pipeline_run_id','stage','started_at'],schema='operations')
  op.create_index('ix_operations_pipeline_stage_runs_fixture_id','pipeline_stage_runs',['fixture_id'],schema='operations')


def downgrade():
 if _has('pipeline_stage_runs','operations'):op.drop_table('pipeline_stage_runs',schema='operations')
 if 'content_hash' in _columns('pipeline_events','operations'):
  op.drop_column('pipeline_events','content_hash',schema='operations')
 for name in ('next_stage','failure_code','quality_score','output_reference','output_version','input_version'):
  if name in _columns('pipeline_stages','operations'):op.drop_column('pipeline_stages',name,schema='operations')
 if 'details' in _columns('forecasts','predictions'):op.drop_column('forecasts','details',schema='predictions')
 if _has('team_statistics','research'):op.drop_table('team_statistics',schema='research')
 for name in ('away_team_id','home_team_id'):
  if name in _columns('fixtures','fixtures'):op.drop_column('fixtures',name,schema='fixtures')
 if 'country_id' in _columns('competitions','sports'):op.drop_column('competitions','country_id',schema='sports')
 if _has('teams','sports'):op.drop_table('teams',schema='sports')
 if _has('countries','sports'):op.drop_table('countries',schema='sports')
