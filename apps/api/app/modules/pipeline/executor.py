"""Compatibility facade; all execution uses the canonical pipeline runner."""
from sqlalchemy import select
from app.db import models as m

def evidence_for(db,fixture_id):
 records=db.scalars(select(m.StageRecord).where(m.StageRecord.fixture_id==fixture_id,m.StageRecord.status=='PASS')).all()
 return {'paper_only':True,'fixture_ids':[fixture_id] if db.get(m.Fixture,fixture_id) else [],'operation_record_ids':[row.id for row in records]}

def execute_run(db,run):
 from app.modules.pipeline.runner import drive_run
 drive_run(db,run)
 return run
