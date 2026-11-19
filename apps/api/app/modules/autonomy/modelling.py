"""Autonomous model lifecycle: train a challenger from corroborated results, promote only through validation gates.

No human approval step: `governance.promotion.promote_model` computes approval from the challenger's own
chronological out-of-sample holdout (beats baseline Brier and log-loss, calibration error within limit).
A challenger that fails stays a CHALLENGER; any existing ACTIVE model keeps serving.

Training features are produced by the same function as live research evidence
(`open_intelligence.features_for`), using only results dated before each match (no leakage).
"""
from datetime import datetime,timedelta,timezone
from sqlalchemy import select,func
from app.db import models as m
from app.modules.research.league import verified_matches,utc
from app.modules.autonomy.open_intelligence import features_for,cached,COMPETITION

CHECK_EVERY=timedelta(hours=1)
RETRAIN_AFTER=timedelta(days=7)
MIN_NEW_RESULTS=30
MODEL_NAME='Autonomous Bundesliga Logit (home win)'


def examples_from(matches):
 """Chronological leakage-safe examples: features use only matches strictly before the match date."""
 rows=[dict(date=utc(g['kickoff']).date().isoformat(),home=g['home_id'],away=g['away_id'],hg=g['home_score'],ag=g['away_score'],finished=True)
       for g in matches]
 rows.sort(key=lambda r:r['date'])
 out=[]
 for g in sorted(matches,key=lambda g:utc(g['kickoff'])):
  kickoff=utc(g['kickoff'])
  before=(kickoff.date()-timedelta(days=1)).isoformat()
  built=features_for(rows,g['home_id'],g['away_id'],before)
  if built is None:continue
  out.append({'fixture_id':g['id'],'feature_cutoff_at':(kickoff-timedelta(hours=1)).isoformat(),'result_at':(kickoff+timedelta(hours=2)).isoformat(),
              'features':built[0],'outcome':1 if g['home_score']>g['away_score'] else 0})
 return out


def train_if_due(factory,at=None):
 at=at or datetime.now(timezone.utc)
 with factory.begin() as db:
  state=cached(db,'autonomy:modelling',None)
  if state.next_check_at and utc(state.next_check_at)>at:return {'status':'NOT_DUE'}
  state.next_check_at=at+CHECK_EVERY
 with factory() as db:
  comp=db.scalar(select(m.Competition).where(m.Competition.name==COMPETITION,m.Competition.country=='Germany'))
  if comp is None:return {'status':'NO_COMPETITION'}
  matches=verified_matches(db,comp.id,at)
  from app.modules.prediction.market_model import model_type
  active=next((x for x in db.scalars(select(m.ModelVersion).where(m.ModelVersion.sport_id==comp.sport_id,m.ModelVersion.status=='ACTIVE')) if model_type(x)=='logistic'),None)
  last=(db.get(m.ProviderSyncState,'autonomy:modelling').payload or {})
 trained_on=int(last.get('trained_on') or 0);last_at=last.get('trained_at')
 grown=len(matches)-trained_on>=MIN_NEW_RESULTS
 # Retrain weekly when enough new results arrived, or sooner while history is still backfilling (<80% used).
 if active and last_at and not (grown and (at-datetime.fromisoformat(last_at)>=RETRAIN_AFTER or trained_on<0.8*len(matches))):
  return {'status':'CURRENT','active_model':active.id,'verified_results':len(matches)}
 if not active and last_at and len(matches)-trained_on<MIN_NEW_RESULTS and at-datetime.fromisoformat(last_at)<timedelta(days=1):
  return {'status':'WAITING_FOR_MORE_RESULTS','verified_results':len(matches),'last_attempt':last}
 examples=examples_from(matches)
 if len(examples)<80:return {'status':'INSUFFICIENT_HISTORY','examples':len(examples),'verified_results':len(matches)}
 from app.modules.prediction.service import create_challenger
 from app.modules.governance.promotion import promote_model
 with factory.begin() as db:
  created=create_challenger(db,comp.sport_id,MODEL_NAME,at.strftime('%Y%m%d.%H%M%S'),examples)
 with factory.begin() as db:
  decision=promote_model(db,created['id'],actor='autonomous-model-governance',at=at)
  state=cached(db,'autonomy:modelling',None)
  state.payload={'trained_on':len(matches),'trained_at':at.isoformat(),'examples':len(examples),'model_id':created['id'],
                 'promoted':bool(decision.get('promoted')),'reasons':decision.get('reasons',[])}
 return {'status':'PROMOTED' if decision.get('promoted') else 'REJECTED','model_id':created['id'],'examples':len(examples),'reasons':decision.get('reasons',[])}


MARKET_RETRAIN=timedelta(days=7)


MIN_MARKET_HISTORY=300


def _train_competition(factory,comp_id,state_key,at):
 from app.modules.prediction import market_model
 with factory.begin() as db:
  comp=db.get(m.Competition,comp_id)
  state=cached(db,state_key,None)
  active=market_model.active_model(db,comp.sport_id,comp.id)
  last=(state.payload or {}).get('trained_at')
  if (state.next_check_at and utc(state.next_check_at)>at) or (active and last and at-datetime.fromisoformat(last)<MARKET_RETRAIN):return {'status':'CURRENT' if active else 'NOT_DUE'}
  state.next_check_at=at+CHECK_EVERY
  if len(verified_matches(db,comp.id,at))<MIN_MARKET_HISTORY:return {'status':'INSUFFICIENT_HISTORY'}
  report=market_model.train(db,comp.sport_id,comp.id,at)
  state.payload={**report,'trained_at':at.isoformat()}
 return report


def train_market_model_if_due(factory,at=None):
 """Weekly (or when none is active) per-outcome validation of a Poisson market model PER COMPETITION.

 A model forecasts only the competition it was validated on. The Bundesliga keeps its original schedule state;
 any other football competition with enough corroborated results gets its own model (see window_corroboration)."""
 at=at or datetime.now(timezone.utc)
 with factory() as db:
  comp=db.scalar(select(m.Competition).where(m.Competition.name==COMPETITION,m.Competition.country=='Germany'))
  others=db.scalars(select(m.Fixture.competition_id).join(m.Result,m.Result.fixture_id==m.Fixture.id)
                    .join(m.Competition,m.Competition.id==m.Fixture.competition_id).join(m.Sport,m.Sport.id==m.Competition.sport_id)
                    .where(m.Sport.name=='Football').group_by(m.Fixture.competition_id)
                    .having(func.count(func.distinct(m.Fixture.id))>=MIN_MARKET_HISTORY)).all()
 report=_train_competition(factory,comp.id,'autonomy:market-model',at) if comp else {'status':'NO_COMPETITION'}
 extra={}
 for comp_id in others:
  if comp and comp_id==comp.id:continue
  try:extra[comp_id]=_train_competition(factory,comp_id,'autonomy:market-model:'+comp_id,at)
  except Exception as exc:extra[comp_id]={'status':'ERROR','code':type(exc).__name__,'detail':str(exc)[:160]}
 if extra:report={**report,'other_competitions':extra}
 return report
