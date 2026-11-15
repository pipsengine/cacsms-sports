"""Transactional outbox: data commits wake the single canonical runner."""
import hashlib,json
from datetime import datetime,timezone
from uuid import uuid4
from sqlalchemy import event,inspect
from sqlalchemy.orm import Session

ENTITIES={'Fixture','Observation','Odds','ModelVersion','Research','Feature','Result','Source','Qualification','Ticket','Betslip','TicketVerification'}


def publish_changes(session,flush_context):
 from app.db import models as m
 connection=session.connection();dialect=connection.dialect.name
 if dialect not in ('postgresql','sqlite'):return
 from sqlalchemy.dialects.postgresql import insert as pg_insert
 from sqlalchemy.dialects.sqlite import insert as sqlite_insert
 insert=pg_insert if dialect=='postgresql' else sqlite_insert
 for obj in list(session.new)+list(session.dirty):
  name=type(obj).__name__
  if name not in ENTITIES or not getattr(obj,'id',None):continue
  if obj in session.dirty and not session.is_modified(obj,include_collections=False):continue
  values={a.key:getattr(obj,a.key,None) for a in inspect(obj).mapper.column_attrs}
  digest=hashlib.sha256(json.dumps([name,values],sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
  fixture_id=obj.id if name=='Fixture' else getattr(obj,'fixture_id',None)
  stamp=datetime.now(timezone.utc)
  statement=insert(m.PipelineEvent).values(id=str(uuid4()),event_key=digest,fixture_id=fixture_id,kind=name.lower()+'.changed',
       payload={'entity':name,'record_id':obj.id},status='PENDING',attempts=0,available_at=stamp,created_at=stamp)
  connection.execute(statement.on_conflict_do_nothing(index_elements=['event_key']))


def install():
 if not event.contains(Session,'after_flush',publish_changes):event.listen(Session,'after_flush',publish_changes)



def publish_configuration(factory):
 """A configuration change is a durable wake-up, not a request to bypass gates."""
 import os
 from app.db import models as m
 keys=('SPORTS_SOURCE_FEEDS_JSON','SPORTS_DISCOVERY_FEEDS_JSON','SPORTS_RESEARCH_QUORUM_JSON','SPORTS_OPENLIGADB_ENABLED')
 digest=hashlib.sha256(json.dumps(['pipeline-configuration',{key:os.getenv(key,'') for key in keys}],sort_keys=True).encode()).hexdigest()
 with factory.begin() as db:
  dialect=db.bind.dialect.name
  if dialect not in ('postgresql','sqlite'):return
  from sqlalchemy.dialects.postgresql import insert as pg_insert
  from sqlalchemy.dialects.sqlite import insert as sqlite_insert
  stamp=datetime.now(timezone.utc)
  statement=(pg_insert if dialect=='postgresql' else sqlite_insert)(m.PipelineEvent).values(id=str(uuid4()),event_key=digest,kind='configuration.changed',fixture_id=None,payload={'entity':'Configuration'},status='PENDING',attempts=0,available_at=stamp,created_at=stamp)
  db.execute(statement.on_conflict_do_nothing(index_elements=['event_key']))
