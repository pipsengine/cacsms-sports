"""Source Intelligence workspace: evidence-backed overview, health and analytics.

Authorization and status come from persisted provider, sync and job records only.
No simulated provider connections or invented success metrics.
"""
from datetime import datetime,timedelta,timezone
from collections import Counter
from sqlalchemy import select,func
from app.db import models as m
from app.modules.acquisition.source_policy import registry
from app.modules.autonomy.service import runtime_status
from app.modules.research.league import utc

PIPELINE=('Discover','Authorize','Collect','Validate','Register','Sync')


def _now(at=None):
 return at or datetime.now(timezone.utc)


def _stamp(value):
 if value is None:return None
 try:return utc(value).isoformat()
 except Exception:return value.isoformat() if hasattr(value,'isoformat') else str(value)


def overview(db,at=None):
 """KPI snapshot and acquisition pipeline status for the Source Intelligence page."""
 at=_now(at)
 rows=registry(db,at)
 jobs=db.scalars(select(m.AcquisitionJob).order_by(m.AcquisitionJob.created_at.desc()).limit(500)).all()
 active=[r for r in rows if r['status']=='ACTIVE']
 healthy=[r for r in active if (r.get('sync_failures') or 0)==0]
 degraded=[r for r in active if (r.get('sync_failures') or 0)>0]
 prohibited=[r for r in rows if r['status']=='PROHIBITED']
 offline=[r for r in rows if r['status']=='DISABLED']
 failed_jobs=sum(1 for j in jobs if j.status=='FAILED')
 succeeded_jobs=sum(1 for j in jobs if j.status=='COMPLETED')
 pending_jobs=sum(1 for j in jobs if j.status in ('PENDING','RETRY_SCHEDULED','RUNNING','PROCESSING'))
 last_syncs=[r['last_sync'] for r in rows if r.get('last_sync')]
 next_syncs=[r['next_sync'] for r in rows if r.get('next_sync')]
 last_sync=max(last_syncs) if last_syncs else None
 next_sync=min(next_syncs) if next_syncs else None
 runtime=runtime_status(db,at)
 authorized=sum(1 for r in rows if r['permission']=='AUTHORIZED')
 observations=sum(int(r.get('observations') or 0) for r in rows)
 has_authorized=authorized>0
 has_collection=observations>0 or succeeded_jobs>0
 sports=db.scalar(select(func.count()).select_from(m.Sport)) or 0
 competitions=db.scalar(select(func.count()).select_from(m.Competition)) or 0
 countries=db.scalar(select(func.count(func.distinct(m.Competition.country))).where(m.Competition.country.is_not(None))) or 0
 seasons=db.scalar(select(func.count()).select_from(m.CompetitionSeason)) or 0
 sync_states=db.scalars(select(m.ProviderSyncState)).all()
 schedule=[{
  'id':state.id,'source_id':state.source_id,'failures':state.failures or 0,
  'last_full_at':_stamp(state.last_full_at),'next_check_at':_stamp(state.next_check_at),
  'last_change':state.last_change,
 } for state in sorted(sync_states,key=lambda s:(s.next_check_at or at,s.id))[:12]]
 report=runtime.get('report') or {}
 open_intel=report.get('open_intelligence') if isinstance(report,dict) else None
 intel_steps=[]
 if isinstance(open_intel,dict):
  for key,value in open_intel.items():
   if key in ('enabled','errors'):continue
   intel_steps.append({'step':key,'status':'RECORDED' if value is not None else 'SKIPPED'})
 pipeline=[{'key':step.lower(),'name':step,'status':'DONE' if (
  step=='Discover' or
  (step=='Authorize' and has_authorized) or
  (step=='Collect' and has_collection) or
  (step=='Validate' and has_collection) or
  (step=='Register' and len(rows)>0) or
  (step=='Sync' and last_sync is not None)
 ) else 'PENDING'} for step in PIPELINE]
 return {
  'mode':'PAPER','updated_at':_stamp(at),
  'autonomous':True,
  'runtime':{
   'worker_online':bool(runtime.get('worker_online')),
   'status':runtime.get('status'),
   'next_run_at':_stamp(runtime.get('next_run_at')),
   'last_success_at':_stamp(runtime.get('last_success_at')),
   'cycles':runtime.get('cycles') or 0,
   'interval_seconds':runtime.get('interval_seconds') or 30,
   'open_intelligence_enabled':bool(isinstance(open_intel,dict) and open_intel.get('enabled')),
   'open_intelligence_steps':intel_steps,
   'blockers':list((report.get('blockers') or [])[:6]) if isinstance(report,dict) else [],
  },
  'coverage':{
   'sports':sports,'countries':countries,'competitions':competitions,'seasons':seasons,
   'authorized_sources':authorized,'observations':observations,
  },
  'schedule':schedule,
  'kpis':{
   'active_sources':len(active),
   'authorized_sources':authorized,
   'acquisition_jobs':len(jobs),
   'pending_jobs':pending_jobs,
   'healthy':len(healthy),
   'degraded':len(degraded),
   'errors':failed_jobs+len(offline),
   'failed_jobs':failed_jobs,
   'successful_jobs':succeeded_jobs,
   'observations':observations,
   'last_sync':_stamp(last_sync),
   'next_sync':_stamp(next_sync or runtime.get('next_run_at')),
  },
  'health':{
   'total':len(rows),'healthy':len(healthy),'degraded':len(degraded),
   'offline':len(offline),'prohibited':len(prohibited),
   'pct_healthy':round(100*len(healthy)/len(active),1) if active else 0,
  },
  'pipeline':pipeline,
  'notice':'Source acquisition runs continuously under the autonomous controller. Authorization is enforced server-side. No simulated provider connections, success states or observations.',
 }


def health(db,at=None):
 """Structured health summary plus per-source registry rows."""
 at=_now(at)
 snap=overview(db,at)
 rows=registry(db,at)
 return {**snap['health'],'mode':'PAPER','updated_at':snap['updated_at'],'sources':rows}


def analytics(db,at=None):
 """Acquisition activity and sport distribution derived from persisted records."""
 at=_now(at)
 rows=registry(db,at)
 jobs=db.scalars(select(m.AcquisitionJob).order_by(m.AcquisitionJob.created_at.desc()).limit(1000)).all()
 since=at-timedelta(hours=24)
 recent=[j for j in jobs if j.created_at and utc(j.created_at)>=since]
 # Hourly buckets for the last 24 hours (actual job counts only).
 buckets=[]
 for i in range(24):
  start=(at-timedelta(hours=23-i)).replace(minute=0,second=0,microsecond=0)
  end=start+timedelta(hours=1)
  count=sum(1 for j in recent if start<=utc(j.created_at)<end)
  buckets.append({'hour':_stamp(start),'jobs':count})
 # Sport distribution from competitions that have recorded observations.
 sport_counts=dict(db.execute(
  select(m.Sport.name,func.count(func.distinct(m.Observation.id)))
  .select_from(m.Observation)
  .join(m.Fixture,m.Observation.fixture_id==m.Fixture.id)
  .join(m.Competition,m.Fixture.competition_id==m.Competition.id)
  .join(m.Sport,m.Competition.sport_id==m.Sport.id)
  .group_by(m.Sport.name)
 ).all())
 if not sport_counts:
  # Fall back to registered competitions when no observations exist yet.
  sport_counts=dict(db.execute(select(m.Sport.name,func.count()).select_from(m.Competition).join(m.Sport).group_by(m.Sport.name)).all())
 total=sum(sport_counts.values()) or 1
 sports=[{'name':name,'count':count,'pct':round(100*count/total,1)} for name,count in sorted(sport_counts.items(),key=lambda x:-x[1])]
 return {
  'mode':'PAPER',
  'sources':len(rows),
  'authorized':sum(1 for r in rows if r['permission']=='AUTHORIZED'),
  'jobs':len(jobs),
  'successful_jobs':sum(1 for j in jobs if j.status=='COMPLETED'),
  'failed_jobs':sum(1 for j in jobs if j.status=='FAILED'),
  'observations':sum(int(r.get('observations') or 0) for r in rows),
  'sports':sports,
  'activity_24h':buckets,
  'job_status':dict(Counter(j.status for j in jobs)),
 }


def acquisition_jobs(db,limit=100):
 jobs=db.scalars(select(m.AcquisitionJob).order_by(m.AcquisitionJob.created_at.desc()).limit(limit)).all()
 names={s.id:s.name for s in db.scalars(select(m.Source)).all()}
 return [{
  'id':j.id,'source_id':j.source_id,'source':names.get(j.source_id,'—'),
  'fixture_id':j.fixture_id,'section':j.section,'status':j.status,
  'attempts':j.attempts,'max_attempts':j.max_attempts,
  'started_at':_stamp(j.created_at),'updated_at':_stamp(j.updated_at),
  'error':j.error_code,'observation_id':j.observation_id,
  'observations':1 if j.observation_id else 0,
 } for j in jobs]
