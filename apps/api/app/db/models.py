import uuid
from datetime import date,datetime,timezone
from sqlalchemy import String,Date,DateTime,ForeignKey,Numeric,Boolean,Text,UniqueConstraint,CheckConstraint,Index,JSON,BigInteger,Integer
from sqlalchemy.orm import Mapped,mapped_column,relationship
from app.db.base import Base

def uid():return str(uuid.uuid4())
def now():return datetime.now(timezone.utc)
class Sport(Base):
 __tablename__='sports';__table_args__={'schema':'sports'}
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 name:Mapped[str]=mapped_column(String(100),unique=True)
class Country(Base):
 __tablename__='countries';__table_args__=(UniqueConstraint('canonical_key',name='country_canonical_key'),{'schema':'sports'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 name:Mapped[str]=mapped_column(String(100))
 canonical_key:Mapped[str]=mapped_column(String(100))
 code:Mapped[str|None]=mapped_column(String(3))
class Competition(Base):
 __tablename__='competitions';__table_args__={'schema':'sports'}
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 sport_id:Mapped[str]=mapped_column(ForeignKey('sports.sports.id'))
 name:Mapped[str]=mapped_column(String(200))
 country:Mapped[str|None]=mapped_column(String(100))
 country_id:Mapped[str|None]=mapped_column(ForeignKey('sports.countries.id'))
class Team(Base):
 __tablename__='teams';__table_args__=(UniqueConstraint('sport_id','canonical_key',name='team_canonical_key'),{'schema':'sports'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 sport_id:Mapped[str]=mapped_column(ForeignKey('sports.sports.id'))
 country_id:Mapped[str|None]=mapped_column(ForeignKey('sports.countries.id'))
 name:Mapped[str]=mapped_column(String(200))
 canonical_key:Mapped[str]=mapped_column(String(200))
class Fixture(Base):
 __tablename__='fixtures';__table_args__=(UniqueConstraint('competition_id','home_name','away_name','kickoff_at',name='canonical_fixture'),{'schema':'fixtures'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 competition_id:Mapped[str]=mapped_column(ForeignKey('sports.competitions.id'))
 season_id:Mapped[str|None]=mapped_column(ForeignKey('sports.competition_seasons.id'),index=True)
 home_name:Mapped[str]=mapped_column(String(200))
 away_name:Mapped[str]=mapped_column(String(200))
 home_team_id:Mapped[str|None]=mapped_column(ForeignKey('sports.teams.id'))
 away_team_id:Mapped[str|None]=mapped_column(ForeignKey('sports.teams.id'))
 kickoff_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),index=True)
 status:Mapped[str]=mapped_column(String(30),default='SCHEDULED')
 competition:Mapped['Competition']=relationship()

 @property
 def sport_id(self):return self.competition.sport_id
class Source(Base):
 __tablename__='providers';__table_args__={'schema':'sources'}
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 name:Mapped[str]=mapped_column(String(120),unique=True)
 permission:Mapped[str]=mapped_column(String(30),default='UNVERIFIED')
 enabled:Mapped[bool]=mapped_column(Boolean,default=False)
class Observation(Base):
 __tablename__='observations';__table_args__=(UniqueConstraint('source_id','content_hash',name='source_hash'),{'schema':'sources'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 source_id:Mapped[str]=mapped_column(ForeignKey('sources.providers.id'))
 fixture_id:Mapped[str|None]=mapped_column(ForeignKey('fixtures.fixtures.id'))
 source_url:Mapped[str|None]=mapped_column(Text)
 content_hash:Mapped[str]=mapped_column(String(64))
 observed_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
 payload:Mapped[dict]=mapped_column(JSON)
class Research(Base):
 __tablename__='dossiers';__table_args__=(UniqueConstraint('fixture_id','version'),{'schema':'research'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 fixture_id:Mapped[str]=mapped_column(ForeignKey('fixtures.fixtures.id'))
 version:Mapped[int]=mapped_column(Integer)
 status:Mapped[str]=mapped_column(String(30))
 sections:Mapped[dict]=mapped_column(JSON)
 evidence_ids:Mapped[list]=mapped_column(JSON)
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class Feature(Base):
 __tablename__='snapshots';__table_args__={'schema':'features'}
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 research_id:Mapped[str]=mapped_column(ForeignKey('research.dossiers.id'))
 cutoff_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
 features:Mapped[dict]=mapped_column(JSON)
class ModelVersion(Base):
 __tablename__='versions';__table_args__={'schema':'models'}
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 sport_id:Mapped[str]=mapped_column(ForeignKey('sports.sports.id'))
 name:Mapped[str]=mapped_column(String(120))
 version:Mapped[str]=mapped_column(String(40))
 status:Mapped[str]=mapped_column(String(30),default='CHALLENGER')
 validation:Mapped[dict]=mapped_column(JSON,default=dict)
class Prediction(Base):
 __tablename__='forecasts';__table_args__={'schema':'predictions'}
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 fixture_id:Mapped[str]=mapped_column(ForeignKey('fixtures.fixtures.id'))
 feature_id:Mapped[str]=mapped_column(ForeignKey('features.snapshots.id'))
 model_id:Mapped[str]=mapped_column(ForeignKey('models.versions.id'))
 market_key:Mapped[str]=mapped_column(String(100))
 outcome_key:Mapped[str]=mapped_column(String(100))
 probability:Mapped[float]=mapped_column(Numeric(9,7))
 predicted_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
 # Uncertainty interval and per-feature explanation computed from the approved artifact.
 details:Mapped[dict|None]=mapped_column(JSON,default=dict)
class Odds(Base):
 __tablename__='odds_snapshots';__table_args__=(CheckConstraint('decimal_odds > 1',name='positive_odds'),{'schema':'markets'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 fixture_id:Mapped[str]=mapped_column(ForeignKey('fixtures.fixtures.id'))
 bookmaker:Mapped[str]=mapped_column(String(60))
 market_key:Mapped[str]=mapped_column(String(100))
 outcome_key:Mapped[str]=mapped_column(String(100))
 decimal_odds:Mapped[float]=mapped_column(Numeric(12,5))
 observed_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
class Qualification(Base):
 __tablename__='decisions';__table_args__={'schema':'qualification'}
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 prediction_id:Mapped[str]=mapped_column(ForeignKey('predictions.forecasts.id'))
 odds_id:Mapped[str]=mapped_column(ForeignKey('markets.odds_snapshots.id'))
 gates:Mapped[dict]=mapped_column(JSON)
 decision:Mapped[str]=mapped_column(String(30))
 decided_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class Programme(Base):
 __tablename__='programmes';__table_args__={'schema':'strategies'}
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 key:Mapped[str]=mapped_column(String(50),unique=True)
 configuration:Mapped[dict]=mapped_column(JSON,default=dict)
class Ticket(Base):
 __tablename__='tickets';__table_args__={'schema':'tickets'}
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 programme_id:Mapped[str]=mapped_column(ForeignKey('strategies.programmes.id'))
 status:Mapped[str]=mapped_column(String(30),default='PAPER_DRAFT')
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class TicketLeg(Base):
 __tablename__='ticket_legs';__table_args__=(UniqueConstraint('ticket_id','qualification_id'),{'schema':'tickets'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 ticket_id:Mapped[str]=mapped_column(ForeignKey('tickets.tickets.id'))
 qualification_id:Mapped[str]=mapped_column(ForeignKey('qualification.decisions.id'))
class BookingCode(Base):
 __tablename__='booking_codes';__table_args__=(UniqueConstraint('bookmaker','code'),{'schema':'tickets'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 ticket_id:Mapped[str]=mapped_column(ForeignKey('tickets.tickets.id'))
 bookmaker:Mapped[str]=mapped_column(String(60))
 code:Mapped[str]=mapped_column(String(100))
 verified_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
 evidence_url:Mapped[str]=mapped_column(Text)
class Result(Base):
 __tablename__='official_results';__table_args__=(UniqueConstraint('fixture_id','version'),{'schema':'results'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 fixture_id:Mapped[str]=mapped_column(ForeignKey('fixtures.fixtures.id'))
 version:Mapped[int]=mapped_column(Integer)
 outcome:Mapped[dict]=mapped_column(JSON)
 verified_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
class Settlement(Base):
 __tablename__='settlements';__table_args__=(UniqueConstraint('prediction_id','result_id'),{'schema':'results'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 prediction_id:Mapped[str]=mapped_column(ForeignKey('predictions.forecasts.id'))
 result_id:Mapped[str]=mapped_column(ForeignKey('results.official_results.id'))
 outcome:Mapped[str]=mapped_column(String(40))
class Mission(Base):
 __tablename__='missions';__table_args__={'schema':'operations'}
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 name:Mapped[str]=mapped_column(String(120))
 status:Mapped[str]=mapped_column(String(30),default='PENDING')
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
class Incident(Base):
 __tablename__='incidents';__table_args__={'schema':'operations'}
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 severity:Mapped[str]=mapped_column(String(15))
 message:Mapped[str]=mapped_column(Text)
 status:Mapped[str]=mapped_column(String(30),default='OPEN')
class AuditEvent(Base):
 __tablename__='events';__table_args__={'schema':'audit'}
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 actor:Mapped[str]=mapped_column(String(100))
 action:Mapped[str]=mapped_column(String(150))
 correlation_id:Mapped[str]=mapped_column(String(36))
 payload:Mapped[dict]=mapped_column(JSON)
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class AcquisitionJob(Base):
 __tablename__='acquisition_jobs';__table_args__=(UniqueConstraint('idempotency_key',name='acquisition_job_key'),{'schema':'operations'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 source_id:Mapped[str]=mapped_column(ForeignKey('sources.providers.id'))
 fixture_id:Mapped[str]=mapped_column(ForeignKey('fixtures.fixtures.id'))
 section:Mapped[str]=mapped_column(String(40))
 idempotency_key:Mapped[str]=mapped_column(String(128))
 status:Mapped[str]=mapped_column(String(30),default='PENDING')
 attempts:Mapped[int]=mapped_column(Integer,default=0)
 max_attempts:Mapped[int]=mapped_column(Integer,default=3)
 lease_until:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
 next_run_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
 updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
 error_code:Mapped[str|None]=mapped_column(String(80))
 observation_id:Mapped[str|None]=mapped_column(ForeignKey('sources.observations.id'))

class StrategyRun(Base):
 __tablename__='runs';__table_args__=(UniqueConstraint('programme_key','idempotency_key',name='strategy_run_unique'),{'schema':'strategies'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 programme_key:Mapped[str]=mapped_column(String(50),index=True)
 idempotency_key:Mapped[str]=mapped_column(String(128))
 status:Mapped[str]=mapped_column(String(30),default='COMPLETED')
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
 result:Mapped[dict]=mapped_column(JSON,default=dict)


class Betslip(Base):
 __tablename__='betslips';__table_args__=(UniqueConstraint('ticket_id',name='betslip_ticket_unique'),{'schema':'tickets'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 ticket_id:Mapped[str]=mapped_column(ForeignKey('tickets.tickets.id'),nullable=False)
 bookmaker:Mapped[str]=mapped_column(String(60),default='SportyBet')
 status:Mapped[str]=mapped_column(String(32),default='PAPER_PREPARED')
 selections:Mapped[list]=mapped_column(JSON,nullable=False)
 combined_odds:Mapped[float]=mapped_column(Numeric(16,5),nullable=False)
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class TicketVerification(Base):
 __tablename__='ticket_verifications';__table_args__={'schema':'tickets'}
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 ticket_id:Mapped[str]=mapped_column(ForeignKey('tickets.tickets.id'),nullable=False,index=True)
 status:Mapped[str]=mapped_column(String(30),nullable=False)
 reason_codes:Mapped[list]=mapped_column(JSON,default=list)
 evidence:Mapped[dict]=mapped_column(JSON,default=dict)
 verified_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class ResultEvidence(Base):
 __tablename__='result_evidence';__table_args__=(UniqueConstraint('result_id','observation_id',name='result_evidence_unique'),{'schema':'results'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 result_id:Mapped[str]=mapped_column(ForeignKey('results.official_results.id'),nullable=False)
 source_id:Mapped[str]=mapped_column(ForeignKey('sources.providers.id'),nullable=False)
 observation_id:Mapped[str]=mapped_column(ForeignKey('sources.observations.id'),nullable=False)


class BrowserCapture(Base):
 __tablename__='browser_captures';__table_args__={'schema':'operations'}
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 fixture_id:Mapped[str]=mapped_column(ForeignKey('fixtures.fixtures.id'),nullable=False)
 source_id:Mapped[str]=mapped_column(ForeignKey('sources.providers.id'),nullable=False)
 url:Mapped[str]=mapped_column(Text,nullable=False)
 status:Mapped[str]=mapped_column(String(32),default='PENDING')
 vision_status:Mapped[str]=mapped_column(String(48),default='NOT_PERFORMED')
 evidence_hash:Mapped[str|None]=mapped_column(String(64))
 error:Mapped[str|None]=mapped_column(Text)
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class ModelGovernanceSnapshot(Base):
 __tablename__='governance_snapshots';__table_args__={'schema':'models'}
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 model_id:Mapped[str]=mapped_column(ForeignKey('models.versions.id'),nullable=False,index=True)
 status:Mapped[str]=mapped_column(String(32),nullable=False)
 reasons:Mapped[list]=mapped_column(JSON,default=list)
 reference:Mapped[dict]=mapped_column(JSON,default=dict)
 recent:Mapped[dict]=mapped_column(JSON,default=dict)
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)


class PipelineRun(Base):
 __tablename__='pipeline_runs';__table_args__=(UniqueConstraint('idempotency_key',name='pipeline_idempotency'),{'schema':'operations'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 idempotency_key:Mapped[str]=mapped_column(String(128),nullable=False)
 fixture_id:Mapped[str|None]=mapped_column(String(36))
 status:Mapped[str]=mapped_column(String(30),default='PENDING')
 mode:Mapped[str]=mapped_column(String(20),default='PAPER')
 context:Mapped[dict]=mapped_column(JSON,default=dict)
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
 updated_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)

class PipelineStage(Base):
 __tablename__='pipeline_stages';__table_args__=(UniqueConstraint('run_id','position',name='pipeline_stage_order'),{'schema':'operations'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 run_id:Mapped[str]=mapped_column(ForeignKey('operations.pipeline_runs.id'),index=True)
 position:Mapped[int]=mapped_column(Integer)
 stage_key:Mapped[str]=mapped_column(String(30))
 status:Mapped[str]=mapped_column(String(30),default='PENDING')
 input_payload:Mapped[dict]=mapped_column(JSON,default=dict)
 output_payload:Mapped[dict]=mapped_column(JSON,default=dict)
 evidence_ids:Mapped[list]=mapped_column(JSON,default=list)
 error:Mapped[str|None]=mapped_column(Text)
 retry_count:Mapped[int]=mapped_column(Integer,default=0)
 started_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
 finished_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
 duration_ms:Mapped[int|None]=mapped_column(Integer)
 next_retry_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
 operation_key:Mapped[str|None]=mapped_column(String(64))
 # Latest-state projection of the standard stage data contract (history lives in PipelineStageRun).
 input_version:Mapped[int]=mapped_column(Integer,default=0)
 output_version:Mapped[int]=mapped_column(Integer,default=0)
 output_reference:Mapped[str|None]=mapped_column(String(36))
 quality_score:Mapped[float|None]=mapped_column(Numeric(6,4))
 failure_code:Mapped[str|None]=mapped_column(String(80))
 next_stage:Mapped[str|None]=mapped_column(String(30))


class PipelineStageRun(Base):
 """Immutable, append-only execution history: one row per stage attempt."""
 __tablename__='pipeline_stage_runs';__table_args__=(Index('ix_pipeline_stage_runs_run','pipeline_run_id','stage','started_at'),{'schema':'operations'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 pipeline_run_id:Mapped[str]=mapped_column(ForeignKey('operations.pipeline_runs.id'),nullable=False)
 fixture_id:Mapped[str|None]=mapped_column(String(36),index=True)
 stage:Mapped[str]=mapped_column(String(30),nullable=False)
 status:Mapped[str]=mapped_column(String(30),nullable=False)
 attempt:Mapped[int]=mapped_column(Integer,default=1)
 input_version:Mapped[int]=mapped_column(Integer,default=0)
 output_version:Mapped[int]=mapped_column(Integer,default=0)
 started_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
 completed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
 duration_ms:Mapped[int|None]=mapped_column(Integer)
 evidence_ids:Mapped[list]=mapped_column(JSON,default=list)
 output_reference:Mapped[str|None]=mapped_column(String(36))
 quality_score:Mapped[float|None]=mapped_column(Numeric(6,4))
 failure_code:Mapped[str|None]=mapped_column(String(80))
 failure_reason:Mapped[str|None]=mapped_column(Text)
 next_stage:Mapped[str|None]=mapped_column(String(30))
 details:Mapped[dict]=mapped_column(JSON,default=dict)


class CompetitionSeason(Base):
 __tablename__='competition_seasons'
 __table_args__=(UniqueConstraint('competition_id','label'),CheckConstraint('end_date >= start_date',name='season_date_order'),{'schema':'sports'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 competition_id:Mapped[str]=mapped_column(ForeignKey('sports.competitions.id'))
 label:Mapped[str]=mapped_column(String(100))
 start_date:Mapped[date]=mapped_column(Date)
 end_date:Mapped[date]=mapped_column(Date)
 is_current:Mapped[bool]=mapped_column(Boolean,default=False)

class StandingsSnapshot(Base):
 __tablename__='standings_snapshots'
 __table_args__=(UniqueConstraint('source_id','content_hash'),Index('ix_standings_lookup','competition_id','season_id','captured_at'),{'schema':'research'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 competition_id:Mapped[str]=mapped_column(ForeignKey('sports.competitions.id'))
 season_id:Mapped[str]=mapped_column(ForeignKey('sports.competition_seasons.id'))
 source_id:Mapped[str]=mapped_column(ForeignKey('sources.providers.id'))
 source_url:Mapped[str]=mapped_column(Text)
 source_reference:Mapped[str]=mapped_column(Text)
 content_hash:Mapped[str]=mapped_column(String(64))
 captured_at:Mapped[datetime]=mapped_column(DateTime(timezone=True))
 verified_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
 official:Mapped[bool]=mapped_column(Boolean,default=False)
 scope:Mapped[str]=mapped_column(String(16),default='overall')
 entries:Mapped[list]=mapped_column(JSON)

 review_status:Mapped[str]=mapped_column(String(24),default='VERIFIED')
 reviewed_by:Mapped[str|None]=mapped_column(String(200))
 imported_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
 provenance:Mapped[dict]=mapped_column(JSON,default=dict)


class AutonomousRuntime(Base):
 __tablename__='autonomous_runtime';__table_args__={'schema':'operations'}
 id:Mapped[str]=mapped_column(String(36),primary_key=True)
 owner:Mapped[str|None]=mapped_column(String(36))
 status:Mapped[str]=mapped_column(String(30),default='STARTING')
 started_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
 finished_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
 last_success_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
 lease_until:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
 next_run_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
 cycles:Mapped[int]=mapped_column(Integer,default=0)
 consecutive_errors:Mapped[int]=mapped_column(Integer,default=0)
 report:Mapped[dict]=mapped_column(JSON,default=dict)


class ProviderSyncState(Base):
 __tablename__='provider_sync_state';__table_args__={'schema':'operations'}
 id:Mapped[str]=mapped_column(String(64),primary_key=True)
 source_id:Mapped[str]=mapped_column(ForeignKey('sources.providers.id'))
 last_change:Mapped[str|None]=mapped_column(String(200))
 next_check_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
 last_full_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
 failures:Mapped[int]=mapped_column(Integer,default=0)
 payload:Mapped[dict]=mapped_column(JSON,default=dict)


class PipelineEvent(Base):
 __tablename__='pipeline_events';__table_args__=(UniqueConstraint('event_key'),Index('ix_pipeline_events_due','status','available_at'),{'schema':'operations'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 event_key:Mapped[str]=mapped_column(String(64))
 # Digest of the changed entity state; only de-duplicates against undelivered events.
 content_hash:Mapped[str|None]=mapped_column(String(64),index=True)
 fixture_id:Mapped[str|None]=mapped_column(String(36))
 kind:Mapped[str]=mapped_column(String(80))
 payload:Mapped[dict]=mapped_column(JSON,default=dict)
 status:Mapped[str]=mapped_column(String(24),default='PENDING')
 attempts:Mapped[int]=mapped_column(Integer,default=0)
 available_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
 lease_until:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)
 completed_at:Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
 error_code:Mapped[str|None]=mapped_column(String(100))

class StageRecord(Base):
 __tablename__='stage_records';__table_args__=(UniqueConstraint('operation_key'),Index('ix_stage_records_fixture','fixture_id','kind','created_at'),{'schema':'operations'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 run_id:Mapped[str]=mapped_column(ForeignKey('operations.pipeline_runs.id'))
 fixture_id:Mapped[str]=mapped_column(ForeignKey('fixtures.fixtures.id'))
 stage_key:Mapped[str]=mapped_column(String(30))
 kind:Mapped[str]=mapped_column(String(50))
 operation_key:Mapped[str]=mapped_column(String(64))
 status:Mapped[str]=mapped_column(String(30))
 evidence_ids:Mapped[list]=mapped_column(JSON,default=list)
 details:Mapped[dict]=mapped_column(JSON,default=dict)
 created_at:Mapped[datetime]=mapped_column(DateTime(timezone=True),default=now)



class TeamStatistic(Base):
 """Per-team statistics normalised from authorized acquisition evidence."""
 __tablename__='team_statistics';__table_args__=(UniqueConstraint('team_id','observation_id',name='team_statistic_observation'),{'schema':'research'})
 id:Mapped[str]=mapped_column(String(36),primary_key=True,default=uid)
 team_id:Mapped[str]=mapped_column(ForeignKey('sports.teams.id'),nullable=False,index=True)
 fixture_id:Mapped[str]=mapped_column(ForeignKey('fixtures.fixtures.id'),nullable=False,index=True)
 observation_id:Mapped[str]=mapped_column(ForeignKey('sources.observations.id'),nullable=False)
 source_id:Mapped[str]=mapped_column(ForeignKey('sources.providers.id'),nullable=False)
 section:Mapped[str]=mapped_column(String(40))
 side:Mapped[str]=mapped_column(String(4))
 as_of:Mapped[datetime]=mapped_column(DateTime(timezone=True))
 statistics:Mapped[dict]=mapped_column(JSON,default=dict)


class MarketEvidence(Base):
 __tablename__='odds_evidence';__table_args__={'schema':'markets'}
 odds_id:Mapped[str]=mapped_column(ForeignKey('markets.odds_snapshots.id'),primary_key=True)
 observation_id:Mapped[str]=mapped_column(ForeignKey('sources.observations.id'))
 source_id:Mapped[str]=mapped_column(ForeignKey('sources.providers.id'))

# Every supported data mutation publishes a transactional event in the same commit.
from app.modules.pipeline.events import install as _install_pipeline_events
_install_pipeline_events()
