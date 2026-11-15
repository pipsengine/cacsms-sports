"""Transactional outbox: data commits wake the single canonical runner.

Each event names the earliest stage the change can affect (``invalidate_from``) so the
runner re-executes only that stage; downstream stages re-run only when its output changes.
Writes made by the runner itself are not re-published, so the pipeline does not wake itself.
"""
import hashlib,json
from datetime import datetime,timezone
from uuid import uuid4
from sqlalchemy import event,inspect,select
from sqlalchemy.orm import Session
from app.modules.pipeline.logic import invalidation_stage,ENTITY_STAGE

ENTITIES=set(ENTITY_STAGE)|{'Observation'}
GLOBAL={'Source','ModelVersion'}
RUNNER_FLAG='pipeline_runner_active'


def _fixture_ids(connection,obj,name):
 """Resolve the fixtures a record belongs to without autoflushing the session."""
 from app.db import models as m
 if name=='Fixture':return [obj.id]
 if getattr(obj,'fixture_id',None):return [obj.fixture_id]
 if name=='Feature':
  value=connection.scalar(select(m.Research.fixture_id).where(m.Research.id==obj.research_id))
  return [value] if value else []
 if name=='Qualification':
  value=connection.scalar(select(m.Prediction.fixture_id).where(m.Prediction.id==obj.prediction_id))
  return [value] if value else []
 if name in ('Ticket','Betslip','TicketVerification'):
  ticket_id=obj.id if name=='Ticket' else obj.ticket_id
  rows=connection.execute(select(m.Prediction.fixture_id).select_from(m.TicketLeg)
       .join(m.Qualification,m.Qualification.id==m.TicketLeg.qualification_id)
       .join(m.Prediction,m.Prediction.id==m.Qualification.prediction_id)
       .where(m.TicketLeg.ticket_id==ticket_id)).scalars().all()
  return sorted(set(rows))
 return []


def _insert(connection,dialect,*,content_hash,fixture_id,kind,payload):
 from app.db import models as m
 from sqlalchemy.dialects.postgresql import insert as pg_insert
 from sqlalchemy.dialects.sqlite import insert as sqlite_insert
 # De-duplicate only against undelivered events: a later A->B->A transition must still wake the runner.
 scope=hashlib.sha256((content_hash+':'+(fixture_id or '*')).encode()).hexdigest()
 pending=connection.scalar(select(m.PipelineEvent.id).where(m.PipelineEvent.content_hash==scope,
          m.PipelineEvent.status.in_(['PENDING','RETRY_SCHEDULED'])).limit(1))
 if pending:return
 stamp=datetime.now(timezone.utc)
 insert=pg_insert if dialect=='postgresql' else sqlite_insert
 statement=insert(m.PipelineEvent).values(id=str(uuid4()),event_key=hashlib.sha256((scope+uuid4().hex).encode()).hexdigest(),
      content_hash=scope,fixture_id=fixture_id,kind=kind,payload=payload,status='PENDING',attempts=0,available_at=stamp,created_at=stamp)
 connection.execute(statement.on_conflict_do_nothing(index_elements=['event_key']))


def publish_changes(session,flush_context):
 if session.info.get(RUNNER_FLAG):return
 connection=session.connection();dialect=connection.dialect.name
 if dialect not in ('postgresql','sqlite'):return
 for obj in list(session.new)+list(session.dirty):
  name=type(obj).__name__
  if name not in ENTITIES or not getattr(obj,'id',None):continue
  if obj in session.dirty and not session.is_modified(obj,include_collections=False):continue
  values={a.key:getattr(obj,a.key,None) for a in inspect(obj).mapper.column_attrs}
  digest=hashlib.sha256(json.dumps([name,values],sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
  section=(obj.payload or {}).get('section') if name=='Observation' and isinstance(obj.payload,dict) else None
  stage=invalidation_stage(name,section)
  payload={'entity':name,'record_id':obj.id,'invalidate_from':stage}
  fixtures=[None] if name in GLOBAL else _fixture_ids(connection,obj,name)
  if not fixtures and name=='Observation':fixtures=[None]
  for fixture_id in fixtures:
   _insert(connection,dialect,content_hash=digest,fixture_id=fixture_id,kind=name.lower()+'.changed',payload=payload)


def install():
 if not event.contains(Session,'after_flush',publish_changes):event.listen(Session,'after_flush',publish_changes)


def publish_configuration(factory):
 """A configuration change is a durable wake-up, not a request to bypass gates."""
 import os
 keys=('SPORTS_SOURCE_FEEDS_JSON','SPORTS_DISCOVERY_FEEDS_JSON','SPORTS_RESEARCH_QUORUM_JSON','SPORTS_OPENLIGADB_ENABLED','SPORTS_RESEARCH_DEADLINE_MINUTES')
 digest=hashlib.sha256(json.dumps(['pipeline-configuration',{key:os.getenv(key,'') for key in keys}],sort_keys=True).encode()).hexdigest()
 from app.db import models as m
 with factory.begin() as db:
  dialect=db.bind.dialect.name
  if dialect not in ('postgresql','sqlite'):return
  # Announce only when the configuration differs from the last announced one (A->B->A still wakes).
  latest=db.scalar(select(m.PipelineEvent.content_hash).where(m.PipelineEvent.kind=='configuration.changed').order_by(m.PipelineEvent.created_at.desc()).limit(1))
  if latest==digest:return
  connection=db.connection()
  from sqlalchemy.dialects.postgresql import insert as pg_insert
  from sqlalchemy.dialects.sqlite import insert as sqlite_insert
  stamp=datetime.now(timezone.utc)
  statement=(pg_insert if dialect=='postgresql' else sqlite_insert)(m.PipelineEvent).values(id=str(uuid4()),event_key=hashlib.sha256((digest+uuid4().hex).encode()).hexdigest(),content_hash=digest,
       kind='configuration.changed',fixture_id=None,payload={'entity':'Configuration','invalidate_from':'acquire'},status='PENDING',attempts=0,available_at=stamp,created_at=stamp)
  connection.execute(statement.on_conflict_do_nothing(index_elements=['event_key']))
