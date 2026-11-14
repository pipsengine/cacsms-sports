"""Safe paper-only mission lifecycle. No external actions are invoked."""
from sqlalchemy import select
from app.db import models as m
STATES={'PENDING':{'RUNNING','CANCELLED'},'RUNNING':{'COMPLETED','BLOCKED','FAILED','CANCELLED'},'BLOCKED':{'PENDING','CANCELLED'},'FAILED':{'PENDING','CANCELLED'},'COMPLETED':set(),'CANCELLED':set()}

def create_mission(session,name,actor='administrator'):
    if not name.strip():raise ValueError('Mission name required')
    mission=m.Mission(name=name.strip(),status='PENDING');session.add(mission);session.flush()
    session.add(m.AuditEvent(actor=actor,action='mission.created',correlation_id=mission.id,payload={'mode':'PAPER'}))
    session.flush();return {'id':mission.id,'name':mission.name,'status':mission.status,'mode':'PAPER'}

def transition(session,mission_id,target,actor='administrator'):
    mission=session.get(m.Mission,mission_id)
    if not mission:raise ValueError('Mission not found')
    if target not in STATES[mission.status]:raise ValueError('Invalid mission transition: '+mission.status+' -> '+target)
    previous=mission.status;mission.status=target
    session.add(m.AuditEvent(actor=actor,action='mission.transition',correlation_id=mission.id,payload={'from':previous,'to':target,'mode':'PAPER'}))
    session.flush();return {'id':mission.id,'status':mission.status,'previous_status':previous,'mode':'PAPER'}
