"""One coherent, server-filtered dashboard snapshot with actual operational state."""
from datetime import datetime,timedelta,timezone
from sqlalchemy import select,func
from app.db import models as m
from app.modules.autonomy.service import runtime_status
from app.modules.pipeline.routes import serialize_run
from app.modules.prediction.prospective import REQUIRED_APPROVALS
from app.modules.strategies.optimizer import PROGRAMMES


def snapshot(db,hours=72,at=None):
 at=at or datetime.now(timezone.utc);since=at-timedelta(hours=hours);until=at+timedelta(hours=hours)
 def count(model,*conditions):
  return db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0
 fixtures_count=count(m.Fixture,m.Fixture.kickoff_at>=at,m.Fixture.kickoff_at<=until)
 research_count=count(m.Research,m.Research.created_at>=since,m.Research.created_at<=at)
 prediction_count=count(m.Prediction,m.Prediction.predicted_at>=since,m.Prediction.predicted_at<=at)
 qualified_count=count(m.Qualification,m.Qualification.decision=='QUALIFIED',m.Qualification.decided_at>=since,m.Qualification.decided_at<=at)
 code_count=count(m.BookingCode,m.BookingCode.code.is_not(None),m.BookingCode.evidence_url.is_not(None),m.BookingCode.verified_at>=since,m.BookingCode.verified_at<=at)
 incident_count=count(m.Incident,m.Incident.status=='OPEN')
 upcoming=db.execute(select(m.Fixture,m.Competition,m.Sport).join(m.Competition,m.Fixture.competition_id==m.Competition.id)
   .join(m.Sport,m.Competition.sport_id==m.Sport.id).where(m.Fixture.kickoff_at>=at,m.Fixture.kickoff_at<=until)
   .order_by(m.Fixture.kickoff_at,m.Fixture.id).limit(5)).all()
 opportunity_query=(select(m.Qualification,m.Prediction,m.Odds,m.Fixture,m.Competition,m.Sport)
   .join(m.Prediction,m.Qualification.prediction_id==m.Prediction.id).join(m.Odds,m.Qualification.odds_id==m.Odds.id)
   .join(m.Fixture,m.Prediction.fixture_id==m.Fixture.id).join(m.Competition,m.Fixture.competition_id==m.Competition.id)
   .join(m.Sport,m.Competition.sport_id==m.Sport.id).where(m.Qualification.decision=='QUALIFIED',m.Qualification.decided_at>=since,m.Qualification.decided_at<=at)
   .order_by(m.Qualification.decided_at.desc()))
 opportunities=[];sport_counts={};odds_bands=[0]*6
 for q,p,o,f,c,s in db.execute(opportunity_query):
  sport_counts[s.name]=sport_counts.get(s.name,0)+1
  price=float(o.decimal_odds)
  for i,(low,high) in enumerate(((2,5),(5,10),(10,25),(25,50),(50,100),(100,1000.000001))):
   if low<=price<high:odds_bands[i]+=1;break
  if len(opportunities)<5:
   opportunities.append(dict(id=q.id,fixture_name=f.home_name+' vs '+f.away_name,league=c.name,sport=s.name,market=p.market_key,
      selection=p.outcome_key,odds=price,probability=float(p.probability),status=q.decision,decided_at=q.decided_at))
 models=db.scalars(select(m.ModelVersion).order_by(m.ModelVersion.name)).all()
 approved=[model for model in models if model.status=='ACTIVE' and isinstance(model.validation,dict) and all(model.validation.get(key) is True for key in REQUIRED_APPROVALS)]
 model_rows=[]
 for model in models[:3]:
  governance=db.scalar(select(m.ModelGovernanceSnapshot).where(m.ModelGovernanceSnapshot.model_id==model.id).order_by(m.ModelGovernanceSnapshot.created_at.desc()).limit(1))
  recent=governance.recent if governance else {}
  model_rows.append(dict(id=model.id,name=model.name,status=model.status,brier=recent.get('brier'),calibration_error=recent.get('ece')))
 start=at.astimezone(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)
 programme_rows=[]
 for key,config in PROGRAMMES.items():
  allocation=db.scalar(select(func.count()).select_from(m.Ticket).join(m.Programme,m.Ticket.programme_id==m.Programme.id)
    .where(m.Programme.key==key,m.Ticket.created_at>=start,m.Ticket.created_at<start+timedelta(days=1))) or 0
  programme_rows.append(dict(key=key,allocated_today=allocation,daily_limit=config['daily_cap']))
 runtime=runtime_status(db,at)
 sources=count(m.Source,m.Source.enabled.is_(True),m.Source.permission=='AUTHORIZED')
 observations=count(m.Observation)
 verified_dossiers=count(m.Research,m.Research.status=='VERIFIED')
 qualifications=count(m.Qualification)
 qualified_current=count(m.Qualification,m.Qualification.decision=='QUALIFIED')
 readiness={'Acquisition':{'status':'READY' if sources and observations else 'WAITING','detail':f'{sources} authorized sources / {observations} observations'},
            'Research':{'status':'READY' if verified_dossiers else 'WAITING','detail':f'{verified_dossiers} verified dossiers'},
            'Prediction':{'status':'READY' if approved else 'WAITING','detail':f'{len(approved)} approved active models'},
            'Qualification':{'status':'READY' if qualified_current else 'WAITING','detail':f'{qualifications} decisions / {qualified_current} qualified'}}
 latest=db.scalar(select(m.PipelineRun).order_by(m.PipelineRun.updated_at.desc(),m.PipelineRun.id).limit(1))
 return dict(updated_at=at,period_hours=hours,since=since,until=until,mode='PAPER',runtime=runtime,readiness=readiness,
   summary=dict(api='CONNECTED',database='CONNECTED',fixtures=fixtures_count,research_dossiers=research_count,predictions=prediction_count,
                qualified=qualified_count,booking_codes=code_count,incidents=incident_count),
   latest_run=serialize_run(db,latest) if latest else None,programmes=programme_rows,
   opportunities=opportunities,selection_total=qualified_count,selections_by_sport=sport_counts,odds_bands=odds_bands,
   fixtures=[dict(id=f.id,kickoff_at=f.kickoff_at,name=f.home_name+' vs '+f.away_name,league=c.name,sport=s.name,status=f.status) for f,c,s in upcoming],
   models=model_rows,approved_models=len(approved),registered_models=len(models),
   source_attribution=[dict(name=s.name,licence='ODbL 1.0',url='https://www.openligadb.de/en/license') for s in db.scalars(select(m.Source).where(m.Source.name=='OpenLigaDB (ODbL 1.0)',m.Source.enabled.is_(True)))])
