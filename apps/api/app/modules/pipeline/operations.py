"""Actual operations for the twelve stages; all attestations reference persisted evidence.

An operation either returns a PASS receipt (its validated output) or raises ``Waiting``:
- ``WAITING_FOR_DATA`` / ``BLOCKED``: not settled yet; the runner retries when inputs change.
- ``NO_OPPORTUNITY`` / ``INSUFFICIENT_DATA`` / ``REJECTED``: valid terminal business outcomes,
  persisted as outcome receipts. They are not technical failures.
"""
import hashlib,json,os,math,re
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from sqlalchemy import select,func
from sqlalchemy.exc import IntegrityError
from app.db import models as m
from app.modules.research.league import utc
from app.modules.research.service import SECTIONS,build_dossier
from app.modules.acquisition.service import build_feature_snapshot
from app.modules.prediction.prospective import infer_approved,REQUIRED_APPROVALS
from app.modules.prediction.service import FEATURE_NAMES

CANCELLED={'CANCELLED','CANCELED','ABANDONED'}
QUOTE_MAX_AGE=timedelta(minutes=15)
RESULT_WINDOW=timedelta(days=7)
FEATURE_SECTIONS=('recent_form','match_statistics')
OPTIONAL_SECTIONS=tuple(section for section in SECTIONS if section not in FEATURE_SECTIONS)
SETTLED_SECTION={'VERIFIED','UNAVAILABLE'}


class Waiting(ValueError):
 def __init__(self,reason,evidence=None,state='WAITING_FOR_DATA',code=None,details=None):
  super().__init__(reason);self.evidence=list(evidence or []);self.state=state;self.code=code or state;self.details=details or {}


def receipt(db,run,key,kind,refs,details,at,status='PASS',period=None):
 identity=[run.id,key,kind,sorted(set(refs)),details,period]
 digest=hashlib.sha256(json.dumps(identity,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
 existing=db.scalar(select(m.StageRecord).where(m.StageRecord.operation_key==digest))
 if existing:return existing
 record=m.StageRecord(run_id=run.id,fixture_id=run.fixture_id,stage_key=key,kind=kind,operation_key=digest,
       status=status,evidence_ids=sorted(set(refs)),details=details,created_at=at)
 db.add(record);db.flush();return record


def latest_record(db,run,kind):
 return db.scalar(select(m.StageRecord).where(m.StageRecord.run_id==run.id,m.StageRecord.kind==kind).order_by(m.StageRecord.created_at.desc()).limit(1))


def authorized(db,source_id):
 source=db.get(m.Source,source_id)
 return source is not None and source.enabled and source.permission=='AUTHORIZED'


def model_approved(model):
 return bool(model) and model.status=='ACTIVE' and isinstance(model.validation,dict) and all(model.validation.get(k) is True for k in REQUIRED_APPROVALS)


def data_of(obs):
 content=obs.payload.get('data',obs.payload.get('values',{}))
 if isinstance(content,dict) and content.get('section') and isinstance(content.get('data'),dict):content=content['data']
 return content


def canonical_key(name):return re.sub(r'\s+',' ',name or '').strip().casefold()


def _get_or_create(db,model,lookup,values):
 row=db.scalar(select(model).filter_by(**lookup))
 if row is not None:return row
 try:
  with db.begin_nested():
   row=model(**lookup,**values);db.add(row);db.flush()
 except IntegrityError:
  row=db.scalar(select(model).filter_by(**lookup))
 return row


def deadline_minutes():
 try:return max(0,int(os.getenv('SPORTS_RESEARCH_DEADLINE_MINUTES','60')))
 except ValueError:return 60


# 01 Discover --------------------------------------------------------------------------

def discover(db,run,at):
 fixture=db.get(m.Fixture,run.fixture_id)
 if fixture is None:raise Waiting('No canonical fixture is linked to this run')
 if not isinstance(fixture.kickoff_at,datetime):
  raise Waiting('Fixture has no valid scheduled time',state='BLOCKED',code='KICKOFF_INVALID')
 home,away=(fixture.home_name or '').strip(),(fixture.away_name or '').strip()
 if not home or not away:raise Waiting('Fixture participants are missing',state='BLOCKED',code='PARTICIPANTS_MISSING')
 if canonical_key(home)==canonical_key(away):raise Waiting('Fixture team identities conflict',state='REJECTED',code='PARTICIPANT_CONFLICT')
 status=(fixture.status or '').upper()
 if status in CANCELLED:raise Waiting('Fixture is '+status.lower(),[fixture.id],state='REJECTED',code='FIXTURE_'+status)
 records=db.scalars(select(m.Observation).where(m.Observation.fixture_id==fixture.id)).all()
 refs=[o.id for o in records if authorized(db,o.source_id) and o.content_hash and utc(o.observed_at)<=at]
 if not refs:raise Waiting('Fixture has no currently authorized provenance',code='NO_AUTHORIZED_PROVENANCE')
 competition=db.get(m.Competition,fixture.competition_id)
 if not competition:raise Waiting('Fixture competition identity is missing',state='BLOCKED',code='COMPETITION_MISSING')
 sport=db.get(m.Sport,competition.sport_id)
 if not sport:raise Waiting('Competition sport identity is missing',state='BLOCKED',code='SPORT_MISSING')
 country=None
 if competition.country and canonical_key(competition.country):
  country=_get_or_create(db,m.Country,{'canonical_key':canonical_key(competition.country)},{'name':competition.country.strip()})
  if competition.country_id!=country.id:competition.country_id=country.id
 teams=[]
 for name in (home,away):
  teams.append(_get_or_create(db,m.Team,{'sport_id':sport.id,'canonical_key':canonical_key(name)},{'name':name,'country_id':country.id if country else None}))
 if fixture.home_team_id!=teams[0].id:fixture.home_team_id=teams[0].id
 if fixture.away_team_id!=teams[1].id:fixture.away_team_id=teams[1].id
 return receipt(db,run,'discover','FIXTURE_IDENTIFIED',[fixture.id,*refs],
  {'sport_id':sport.id,'country_id':country.id if country else None,'competition_id':competition.id,'season_id':fixture.season_id,
   'home_team_id':teams[0].id,'away_team_id':teams[1].id,'kickoff_at':utc(fixture.kickoff_at).isoformat(),'fixture_status':fixture.status,
   'quality_score':1.0},at)


# 02 Acquire ---------------------------------------------------------------------------

def materialize_team_statistics(db,fixture,observations):
 ids=[]
 for obs in observations:
  section=obs.payload.get('section')
  if section not in FEATURE_SECTIONS:continue
  content=data_of(obs)
  if not isinstance(content,dict):continue
  for side,team_id in (('home',fixture.home_team_id),('away',fixture.away_team_id)):
   stats={key[len(side)+1:]:value for key,value in content.items() if key.startswith(side+'_')}
   if not team_id or not stats:continue
   row=_get_or_create(db,m.TeamStatistic,{'team_id':team_id,'observation_id':obs.id},
        {'fixture_id':fixture.id,'source_id':obs.source_id,'section':section,'side':side.upper(),'as_of':obs.observed_at,'statistics':stats})
   ids.append(row.id)
 return sorted(ids)


def acquire(db,run,at):
 from app.modules.acquisition.jobs import feed_config,enqueue
 from app.modules.acquisition.service import ALLOWED_SECTIONS
 fixture=db.get(m.Fixture,run.fixture_id)
 feeds=feed_config();jobs=[]
 for source in db.scalars(select(m.Source).where(m.Source.enabled.is_(True),m.Source.permission=='AUTHORIZED')):
  sections=feeds.get(source.id,{})
  if not isinstance(sections,dict):continue
  for section in set(sections)&set(ALLOWED_SECTIONS):
   if utc(fixture.kickoff_at)<=at and section!='official_result':continue
   if utc(fixture.kickoff_at)>at and section=='official_result':continue
   result=enqueue(db,source.id,fixture.id,section,at.strftime('%Y%m%d%H') if section!='market_odds' else at.strftime('%Y%m%d%H%M')[:-1])
   if result['status'] in ('PENDING','RETRY_SCHEDULED'):jobs.append(result['id'])
 run.context={**(run.context or {}),'queued_job_ids':sorted(set(jobs))}
 observations=db.scalars(select(m.Observation).where(m.Observation.fixture_id==run.fixture_id,m.Observation.observed_at<=at)).all()
 valid=[o for o in observations if authorized(db,o.source_id) and o.content_hash]
 if not valid:raise Waiting('Authorized acquisition jobs are queued; awaiting actual observations',jobs,code='AWAITING_OBSERVATIONS')
 coverage={}
 for obs in valid:
  section=obs.payload.get('section') or 'unspecified'
  stamp=utc(obs.observed_at).isoformat()
  if stamp>coverage.get(section,''):coverage[section]=stamp
 statistics=materialize_team_statistics(db,fixture,valid)
 quality=round(len(set(coverage)&set(SECTIONS))/len(SECTIONS),4)
 return receipt(db,run,'acquire','SOURCE_EVIDENCE_ACQUIRED',[o.id for o in valid],
  {'observation_count':len(valid),'latest_by_section':coverage,'missing_sections':[s for s in SECTIONS if s not in coverage],
   'team_statistic_ids':statistics,'quality_score':quality,
   'capture_policy':'Structured feeds or independently reviewed browser evidence; no assumed vision verification'},at)


# 03 Research --------------------------------------------------------------------------

def autonomous_quorum(db):
 """Built-in independence groups for system-registered open-data providers (explicit policy JSON overrides)."""
 from app.modules.autonomy.open_intelligence import GROUPS,enabled
 if not enabled():return {}
 return {sid:{'independence_group':group,'reviewed':True} for sid,group in GROUPS.items() if authorized(db,sid)}


def covered_sections(db):
 """Research sections at least one enabled, authorized source can supply (configured feeds or open-data producers)."""
 from app.modules.acquisition.jobs import feed_config
 from app.modules.autonomy.open_intelligence import PRODUCED_SECTIONS,FD_SOURCE_ID,enabled
 covered=set(PRODUCED_SECTIONS) if enabled() and authorized(db,FD_SOURCE_ID) else set()
 try:feeds=feed_config()
 except ValueError:feeds={}
 for sid,sections in feeds.items():
  if isinstance(sections,dict) and authorized(db,sid):covered|=set(sections)
 # Reviewed corroboration sources push evidence (ingest API, reviewed browser capture) rather than being polled.
 # They may still deliver any section before the deadline unless their policy entry lists the sections they supply,
 # so their pending sections must wait for the research deadline instead of closing as NO_SOURCE_COVERAGE.
 try:policy=json.loads(os.getenv('SPORTS_RESEARCH_QUORUM_JSON') or '{}')
 except ValueError:policy={}
 for sid,entry in (policy.items() if isinstance(policy,dict) else ()):
  if isinstance(entry,dict) and entry.get('reviewed') is True and authorized(db,sid):
   declared=entry.get('sections')
   covered|=set(declared) & set(SECTIONS) if isinstance(declared,list) else set(SECTIONS)
 return covered


def canonical_content(value):
 if isinstance(value,bool) or value is None:return value
 if type(value) in (int,float):
  if not math.isfinite(value):raise Waiting('Research evidence contains a non-finite numeric value',state='BLOCKED',code='NON_FINITE_EVIDENCE')
  return float(value)
 if isinstance(value,list):return [canonical_content(item) for item in value]
 if isinstance(value,dict):return {key:canonical_content(item) for key,item in value.items()}
 return value


def declares_unavailable(obs):
 content=data_of(obs)
 return isinstance(content,dict) and str(content.get('availability','')).upper()=='UNAVAILABLE'


def dossier_summary(dossier):
 sections=dossier.sections or {}
 verified=[k for k in SECTIONS if sections.get(k,{}).get('status')=='VERIFIED']
 unavailable={k:sections[k].get('details',{}).get('reason','Explicitly unavailable') for k in SECTIONS if sections.get(k,{}).get('status')=='UNAVAILABLE'}
 missing={k:sections.get(k,{}).get('status','MISSING') for k in SECTIONS if sections.get(k,{}).get('status') not in SETTLED_SECTION}
 score=round(len(verified)/len(SECTIONS),4)
 methods=sorted({str(sections.get(k,{}).get('details',{}).get('method') or 'REVIEWED_DOSSIER') for k in verified})
 # Derived from the dossier itself, so re-validating an unchanged dossier yields the same receipt.
 return {'dossier_id':dossier.id,'version':dossier.version,'completeness_score':score,'quality_score':score,'verification_methods':methods,
         'verified_sections':verified,'unavailable_sections':unavailable,'missing_data_report':missing}


def research(db,run,at):
 fixture=db.get(m.Fixture,run.fixture_id)
 observations=db.scalars(select(m.Observation).where(m.Observation.fixture_id==fixture.id,m.Observation.observed_at<=at,
     m.Observation.observed_at<fixture.kickoff_at).order_by(m.Observation.observed_at.desc(),m.Observation.id)).all()
 valid=[o for o in observations if authorized(db,o.source_id) and o.content_hash]
 latest=db.scalar(select(m.Research).where(m.Research.fixture_id==fixture.id).order_by(m.Research.version.desc()).limit(1))
 available={o.id for o in valid}
 if latest and latest.status=='VERIFIED' and latest.evidence_ids and set(latest.evidence_ids)<=available and all(latest.sections.get(k,{}).get('status') in SETTLED_SECTION for k in SECTIONS) and not any(o.payload.get('section') in SECTIONS and utc(o.observed_at)>utc(latest.created_at) for o in valid):
  return receipt(db,run,'research','DOSSIER_VERIFIED',[latest.id,*latest.evidence_ids],dossier_summary(latest),at)
 try:policy=json.loads(os.getenv('SPORTS_RESEARCH_QUORUM_JSON') or '{}')
 except ValueError:raise Waiting('Research corroboration policy is invalid',state='BLOCKED',code='POLICY_INVALID')
 if not isinstance(policy,dict):raise Waiting('Research corroboration policy must be an object',state='BLOCKED',code='POLICY_INVALID')
 policy={**autonomous_quorum(db),**policy}
 covered=covered_sections(db)
 deadline_passed=at>=utc(fixture.kickoff_at)-timedelta(minutes=deadline_minutes())
 sections={};refs=[]
 for section in SECTIONS:
  groups={};reviewed=[]
  for obs in valid:
   if obs.payload.get('section')!=section:continue
   if obs.payload.get('verification')=='INDEPENDENT_REVIEW' and obs.payload.get('reviewer') and obs.payload.get('reviewer')!='vision':reviewed.append(obs)
   entry=policy.get(obs.source_id,{})
   group=entry.get('independence_group') if isinstance(entry,dict) and entry.get('reviewed') is True else None
   if isinstance(group,str) and group and group not in groups:groups[group]=obs
  buckets=defaultdict(list)
  for group,obs in groups.items():
   canonical=json.dumps(canonical_content(data_of(obs)),sort_keys=True,separators=(',',':'),allow_nan=False)
   buckets[canonical].append((group,obs))
  quorum=next((items for items in buckets.values() if len(items)>=2),None)
  selected=reviewed[:1] if reviewed else [obs for _,obs in quorum] if quorum else []
  ids=[o.id for o in selected]
  details={'method':'INDEPENDENT_REVIEW' if reviewed else 'CROSS_SOURCE_QUORUM','independence_groups':[g for g,_ in quorum] if quorum else [],'conflict':len(buckets)>1 and not quorum}
  if ids and declares_unavailable(selected[0]):
   # Unavailability is itself corroborated evidence, never assumed.
   sections[section]={'status':'UNAVAILABLE','evidence_ids':ids,'details':{**details,'reason':str(data_of(selected[0]).get('reason') or 'Declared unavailable by corroborated sources')}}
  elif ids:
   sections[section]={'status':'VERIFIED','evidence_ids':ids,'details':details}
  elif section in OPTIONAL_SECTIONS and deadline_passed and not details['conflict']:
   sections[section]={'status':'UNAVAILABLE','evidence_ids':[],'details':{**details,'method':'RESEARCH_DEADLINE','reason':'No corroborated evidence by the pre-kickoff research deadline'}}
  elif section in OPTIONAL_SECTIONS and section not in covered and not details['conflict'] and not any(o.payload.get('section')==section for o in valid):
   # No enabled, authorized source can supply this section: record that fact instead of waiting forever.
   sections[section]={'status':'UNAVAILABLE','evidence_ids':[],'details':{**details,'method':'NO_SOURCE_COVERAGE','reason':'No enabled authorized source provides this section'}}
  else:
   sections[section]={'status':'CONFLICTED' if details['conflict'] else 'PENDING','evidence_ids':[],'details':details}
  refs.extend(ids)
 if not refs:raise Waiting('Research requires independently reviewed evidence or agreement from two configured independent source groups',code='NO_CORROBORATED_EVIDENCE')
 refs=sorted(set(refs))
 if latest and set(latest.evidence_ids)==set(refs) and latest.sections==sections:dossier=latest
 else:
  built=build_dossier(db,fixture.id,sections,refs,at=at);dossier=db.get(m.Research,built['id'])
 summary=dossier_summary(dossier)
 if summary['missing_data_report']:
  raise Waiting('Research sections lack corroboration: '+', '.join(summary['missing_data_report']),[dossier.id],code='SECTIONS_UNCORROBORATED',details=summary)
 return receipt(db,run,'research','DOSSIER_VERIFIED',[dossier.id,*refs],summary,at)


# 04 Analyse ---------------------------------------------------------------------------

def _poisson(rate,goals):return math.exp(-rate)*rate**goals/math.factorial(goals)


def match_analysis(f):
 """Football expected scores and scoring distributions from verified, pre-kickoff rates."""
 home_rate=(f['home_scoring_rate']+f['away_conceding_rate'])/2
 away_rate=(f['away_scoring_rate']+f['home_conceding_rate'])/2
 home=[_poisson(home_rate,k) for k in range(11)];away=[_poisson(away_rate,k) for k in range(11)]
 grid=[(i,j,home[i]*away[j]) for i in range(11) for j in range(11)]
 outcomes={'HOME':sum(p for i,j,p in grid if i>j),'DRAW':sum(p for i,j,p in grid if i==j),'AWAY':sum(p for i,j,p in grid if i<j)}
 top=sorted(grid,key=lambda x:-x[2])[:5]
 attack_home=f['home_scoring_rate']-f['away_conceding_rate'];attack_away=f['away_scoring_rate']-f['home_conceding_rate']
 balance=(f['home_form']-f['away_form'])+(home_rate-away_rate)
 return {'method':'INDEPENDENT_POISSON_FROM_VERIFIED_RATES','expected_score':{'home':round(home_rate,4),'away':round(away_rate,4)},
         'scoring_distribution':{'home':[round(p,6) for p in home[:7]],'away':[round(p,6) for p in away[:7]]},
         'outcome_probabilities':{k:round(v,6) for k,v in outcomes.items()},
         'most_likely_scores':[{'score':f'{i}-{j}','probability':round(p,6)} for i,j,p in top],
         'over_2_5':round(sum(p for i,j,p in grid if i+j>2),6),'both_teams_score':round((1-home[0])*(1-away[0]),6),
         'matchup':{'form_difference':round(f['home_form']-f['away_form'],4),'home_attack_vs_away_defence':round(attack_home,4),
                    'away_attack_vs_home_defence':round(attack_away,4),
                    'assessment':'HOME_ADVANTAGE' if balance>.25 else 'AWAY_ADVANTAGE' if balance<-.25 else 'BALANCED'}}


def analyse(db,run,at):
 fixture=db.get(m.Fixture,run.fixture_id)
 dossier=db.scalar(select(m.Research).where(m.Research.fixture_id==run.fixture_id,m.Research.status=='VERIFIED').order_by(m.Research.version.desc()).limit(1))
 if not dossier:raise Waiting('A verified research dossier is required',code='DOSSIER_REQUIRED')
 if utc(dossier.created_at)>at:raise Waiting('Research dossier post-dates the analysis cutoff',[dossier.id],state='BLOCKED',code='FUTURE_DATA_LEAKAGE')
 for section in FEATURE_SECTIONS:
  if dossier.sections.get(section,{}).get('status')!='VERIFIED':
   raise Waiting('Feature-critical research section is unavailable: '+section,[dossier.id],state='INSUFFICIENT_DATA',code='FEATURE_SECTION_UNAVAILABLE')
 numbers={}
 for section in FEATURE_SECTIONS:
  for ident in dossier.sections.get(section,{}).get('evidence_ids',[]):
   obs=db.get(m.Observation,ident)
   if not obs or not authorized(db,obs.source_id):raise Waiting('Analysis evidence source has been revoked',code='SOURCE_REVOKED')
   if utc(obs.observed_at)>at or utc(obs.observed_at)>=utc(fixture.kickoff_at):
    raise Waiting('Analysis evidence was observed after the cutoff',[obs.id],state='BLOCKED',code='FUTURE_DATA_LEAKAGE')
   content=data_of(obs)
   if isinstance(content,dict):
    for key in FEATURE_NAMES:
     if key in content:
      value=content[key]
      if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=10:raise Waiting('Invalid numeric research feature: '+key,state='BLOCKED',code='INVALID_FEATURE')
      if key in numbers and numbers[key]!=float(value):raise Waiting('Conflicting numeric feature: '+key,state='BLOCKED',code='CONFLICTING_FEATURE')
      numbers[key]=float(value)
 if set(numbers)!=set(FEATURE_NAMES):
  raise Waiting('Verified research lacks the six required sport-specific numeric features',[dossier.id],state='INSUFFICIENT_DATA',code='FEATURES_INCOMPLETE')
 analysis=match_analysis(numbers)
 feature=db.scalar(select(m.Feature).where(m.Feature.research_id==dossier.id).order_by(m.Feature.cutoff_at.desc()).limit(1))
 if feature is None or feature.features.get('numeric_features')!=numbers:
  # Every verified dimension is materialized; explicitly unavailable ones are recorded as such.
  verified=[k for k in SECTIONS if dossier.sections.get(k,{}).get('status')=='VERIFIED']
  built=build_feature_snapshot(db,research_id=dossier.id,cutoff_at=at,required_sections=verified);feature=db.get(m.Feature,built['id'])
 if feature.features.get('numeric_features')!=numbers or feature.features.get('analysis')!=analysis:
  feature.features={**feature.features,'numeric_features':numbers,'analysis':analysis}
 return receipt(db,run,'analyse','FEATURES_MATERIALIZED',[feature.id,dossier.id,*dossier.evidence_ids],
  {'feature_id':feature.id,'cutoff_at':utc(feature.cutoff_at).isoformat(),'feature_names':list(FEATURE_NAMES),
   'expected_score':analysis['expected_score'],'outcome_probabilities':analysis['outcome_probabilities'],
   'matchup':analysis['matchup'],'leakage_check':'PASS','quality_score':dossier_summary(dossier)['completeness_score']},at)


# 05 Predict ---------------------------------------------------------------------------

def predict(db,run,at):
 latest=db.scalar(select(m.Research).where(m.Research.fixture_id==run.fixture_id,m.Research.status=='VERIFIED').order_by(m.Research.version.desc()).limit(1))
 report=infer_approved(db,db.get(m.Fixture,run.fixture_id),now=at,dossier_id=latest.id if latest else None)
 from app.modules.prediction.market_model import infer as infer_markets
 markets=infer_markets(db,db.get(m.Fixture,run.fixture_id),dossier_id=latest.id if latest else None,now=at)
 report={k:report[k]+markets[k] for k in ('created','existing','blocked')}
 refs=report['created']+report['existing']
 if not refs:raise Waiting('; '.join(dict.fromkeys(report['blocked'])) or 'No approved inference artifact can produce a valid forecast',code='NO_APPROVED_MODEL')
 forecasts=[]
 for prediction in db.scalars(select(m.Prediction).where(m.Prediction.id.in_(refs))):
  details=prediction.details or {}
  forecasts.append({'prediction_id':prediction.id,'model_id':prediction.model_id,'market':prediction.market_key,'outcome':prediction.outcome_key,
                    'probability':str(prediction.probability),'interval':details.get('interval'),'top_factors':(details.get('explanation') or {}).get('contributions',[])[:3]})
 return receipt(db,run,'predict','FORECASTS_GENERATED',refs,{'prediction_ids':sorted(refs),'forecasts':sorted(forecasts,key=lambda x:x['prediction_id']),
  'model_policy':'ACTIVE, promoted only after server-side out-of-sample validation and calibration checks'},at)


# 06 Evaluate --------------------------------------------------------------------------

def import_prices(db,fixture_id,at):
 observations=db.scalars(select(m.Observation).where(m.Observation.fixture_id==fixture_id,m.Observation.observed_at<=at).order_by(m.Observation.observed_at.desc(),m.Observation.id)).all()
 seen_sources=set()
 for obs in observations:
  if obs.payload.get('section')!='market_odds' or not authorized(db,obs.source_id) or obs.source_id in seen_sources:continue
  seen_sources.add(obs.source_id)
  prices=data_of(obs).get('prices',[]) if isinstance(data_of(obs),dict) else []
  if not isinstance(prices,list) or len(prices)>100:raise Waiting('Invalid market quote evidence',state='BLOCKED',code='INVALID_QUOTES')
  for row in prices:
   try:
    stamp=datetime.fromisoformat(row['observed_at'].replace('Z','+00:00'));price=Decimal(str(row['decimal_odds']))
    if stamp.tzinfo is None or stamp>at or utc(obs.observed_at)<stamp or not price.is_finite() or not Decimal('1')<price<=1000:raise ValueError()
    if row['market_key']!='1X2' or row['outcome_key'] not in ('HOME','DRAW','AWAY') or not isinstance(row['bookmaker'],str) or not row['bookmaker']:raise ValueError()
   except (ValueError,TypeError,KeyError,ArithmeticError):raise Waiting('Invalid, future or unsupported source-backed price',state='BLOCKED',code='INVALID_QUOTES')
   quote=db.scalar(select(m.Odds).where(m.Odds.fixture_id==fixture_id,m.Odds.bookmaker==row['bookmaker'],m.Odds.market_key==row['market_key'],m.Odds.outcome_key==row['outcome_key'],m.Odds.observed_at==stamp))
   if quote is None:
    quote=m.Odds(fixture_id=fixture_id,bookmaker=row['bookmaker'],market_key=row['market_key'],outcome_key=row['outcome_key'],decimal_odds=price,observed_at=stamp);db.add(quote);db.flush()
   elif Decimal(str(quote.decimal_odds))!=price:raise Waiting('Conflicting source quotes at the same timestamp',state='BLOCKED',code='CONFLICTING_QUOTES')
   if db.get(m.MarketEvidence,quote.id) is None:db.add(m.MarketEvidence(odds_id=quote.id,observation_id=obs.id,source_id=obs.source_id))
 db.flush()


def evaluate(db,run,at):
 import_prices(db,run.fixture_id,at)
 # Market discovery + scan of every observed outcome (throttled; isolated so it can never break evaluation).
 try:
  from app.modules.markets.catalogue import scan as scan_markets
  with db.begin_nested():scan_markets(db,run.fixture_id,at=at,trigger='PIPELINE_EVALUATE')
 except Exception:
  import logging;logging.getLogger(__name__).exception('Market scan failed for fixture %s',run.fixture_id)
 quotes=db.scalars(select(m.Odds).where(m.Odds.fixture_id==run.fixture_id).order_by(m.Odds.observed_at.desc(),m.Odds.id)).all()
 latest={}
 for quote in quotes:
  from app.modules.markets.odds_intelligence import record_assessment
  if record_assessment(db,quote,at)['eligible']:latest.setdefault((quote.bookmaker,quote.market_key,quote.outcome_key),quote)
 forecast=latest_record(db,run,'FORECASTS_GENERATED')
 predictions=db.scalars(select(m.Prediction).where(m.Prediction.fixture_id==run.fixture_id,m.Prediction.id.in_(forecast.evidence_ids if forecast else []))).all()
 pairs=[];rejected=[];refs=[];complete=0
 for prediction in predictions:
  for (book,market,outcome),quote in latest.items():
   if prediction.market_key!=market or prediction.outcome_key!=outcome:continue
   full=[latest.get((book,market,choice)) for choice in ('HOME','DRAW','AWAY')]
   if any(item is None for item in full):continue
   complete+=1
   overround=sum(1/float(item.decimal_odds) for item in full)
   probability=float(prediction.probability);price=float(quote.decimal_odds);implied=1/price
   entry={'prediction_id':prediction.id,'odds_id':quote.id,'bookmaker':book,'market':market,'outcome':outcome,
          'probability':round(probability,7),'decimal_odds':round(price,5),'implied_probability':round(implied,7),
          'fair_probability':round(implied/overround,7),'bookmaker_margin':round(overround-1,7),'overround':round(overround,7),
          'probability_edge':round(probability-implied,7),'expected_value':round(probability*price-1,7),
          'quote_age_seconds':int((at-utc(quote.observed_at)).total_seconds())}
   refs.extend([prediction.id,*[q.id for q in full],*[db.get(m.MarketEvidence,q.id).observation_id for q in full]])
   if not .90<=overround<=1.25:rejected.append({**entry,'reason':'BOOKMAKER_MARGIN_OUT_OF_RANGE'});continue
   if not model_approved(db.get(m.ModelVersion,prediction.model_id)):rejected.append({**entry,'reason':'MODEL_NOT_APPROVED'});continue
   pairs.append({**entry,'market_risk':'PASS'})
 if not complete:
  latest_at=max((utc(q.observed_at) for q in quotes),default=None)
  reason='No complete, source-backed, fresh 1X2 market is available'
  reason+=('; latest stored quote: '+latest_at.isoformat() if latest_at else '; no odds stored for this fixture')
  raise Waiting(reason,code='NO_FRESH_MARKET',details={'stored_quotes':len(quotes),'fresh_source_backed_quotes':len(latest),
      'latest_quote_at':latest_at.isoformat() if latest_at else None,'max_quote_age_seconds':int(QUOTE_MAX_AGE.total_seconds()),
      'required_action':'Supply current authorized odds covering this fixture; collection alone cannot refresh old provider prices'})
 if not pairs:raise Waiting('No fresh market passes model and bookmaker-margin checks',refs,state='NO_OPPORTUNITY',code='MARKET_CHECKS_FAILED',details={'market_evaluations':rejected})
 return receipt(db,run,'evaluate','MARKET_RISK_EVALUATED',refs,{'pairs':pairs,'rejected':rejected,'max_quote_age_seconds':int(QUOTE_MAX_AGE.total_seconds()),
  'overround_range':[.90,1.25],'paper_exposure_only':True},at)


# 07 Qualify ---------------------------------------------------------------------------

def qualify(db,run,at):
 from app.modules.markets.persistence import qualify_from_database
 evaluation=latest_record(db,run,'MARKET_RISK_EVALUATED')
 if evaluation is None:raise Waiting('No market-risk evaluation exists',code='EVALUATION_REQUIRED')
 refs=[];decisions=[]
 for pair in evaluation.details['pairs']:
  previous=db.scalar(select(m.Qualification).where(m.Qualification.prediction_id==pair['prediction_id'],m.Qualification.odds_id==pair['odds_id']).order_by(m.Qualification.decided_at.desc()).limit(1))
  if previous is None:
   result=qualify_from_database(db,pair['prediction_id'],pair['odds_id'],now=at);previous=db.get(m.Qualification,result['id']);previous.decided_at=at
   previous.gates={**previous.gates,'market_risk':'PASS','risk_record_id':evaluation.id}
  from app.modules.markets.odds_intelligence import assess
  quality=assess(db,db.get(m.Odds,pair['odds_id']),at)
  passed=previous.decision=='QUALIFIED' and previous.gates.get('market_risk')=='PASS' and quality['eligible']
  if passed:refs.append(previous.id)
  decisions.append({'qualification_id':previous.id,'decision':'QUALIFIED' if passed else 'REJECTED',
                    'reason_codes':list(dict.fromkeys(previous.gates.get('reason_codes',[])+quality['rejection_reasons'])) or ([] if passed else ['MARKET_RISK_NOT_PASSED']),
                    'metrics':previous.gates.get('metrics',{}),'gates':{k:v for k,v in previous.gates.items() if k not in ('reason_codes','metrics')}})
 if not refs:
  reasons=sorted({code for item in decisions for code in item['reason_codes']})
  raise Waiting('Qualification rejected: '+(', '.join(reasons) or 'no qualifying market'),[d['qualification_id'] for d in decisions],
                state='REJECTED',code='QUALIFICATION_REJECTED',details={'decisions':decisions})
 return receipt(db,run,'qualify','QUALIFICATIONS_PASSED',refs,{'qualification_ids':refs,'decisions':decisions,'market_risk_record_id':evaluation.id},at)


# 08 Allocate --------------------------------------------------------------------------

def allocate(db,run,at):
 from app.modules.strategies.optimizer import Candidate,select_tickets,PROGRAMMES
 passed=latest_record(db,run,'QUALIFICATIONS_PASSED')
 if passed is None:raise Waiting('No qualified selection exists for this fixture',code='QUALIFICATION_REQUIRED')
 # Only live, fresh, not-yet-started qualified selections can share a programme pool.
 rows=db.execute(select(m.Qualification,m.Prediction,m.Odds,m.Fixture)
      .join(m.Prediction,m.Prediction.id==m.Qualification.prediction_id).join(m.Odds,m.Odds.id==m.Qualification.odds_id)
      .join(m.Fixture,m.Fixture.id==m.Prediction.fixture_id)
      .where(m.Qualification.decision=='QUALIFIED',m.Fixture.kickoff_at>at,m.Odds.observed_at<=at,m.Odds.observed_at>=at-QUOTE_MAX_AGE)).all()
 candidates=[];bookmakers={}
 for q,p,price,fixture in rows:
  if q.gates.get('market_risk')!='PASS' or not model_approved(db.get(m.ModelVersion,p.model_id)):continue
  evidence=db.get(m.MarketEvidence,price.id)
  if evidence is None or not authorized(db,evidence.source_id):continue
  from app.modules.markets.odds_intelligence import assess
  if not assess(db,price,at)['eligible']:continue
  feature=db.get(m.Feature,p.feature_id);dossier=db.get(m.Research,feature.research_id) if feature else None
  current=db.scalar(select(m.Research).where(m.Research.fixture_id==fixture.id).order_by(m.Research.version.desc()).limit(1))
  if dossier is None or current is None or current.id!=dossier.id or dossier.status!='VERIFIED':continue
  if any(obs is None or not authorized(db,obs.source_id) for obs in (db.get(m.Observation,ident) for ident in dossier.evidence_ids)):continue
  newest=db.scalar(select(m.Odds.id).where(m.Odds.fixture_id==fixture.id,m.Odds.bookmaker==price.bookmaker,m.Odds.market_key==price.market_key,m.Odds.outcome_key==price.outcome_key,m.Odds.observed_at<=at).order_by(m.Odds.observed_at.desc()).limit(1))
  if newest!=price.id:continue
  candidates.append(Candidate(q.id,fixture.id,Decimal(str(price.decimal_odds)),Decimal(str(p.probability)),p.market_key,p.outcome_key,fixture.kickoff_at.isoformat()))
  bookmakers[q.id]=price.bookmaker
 eligible={c.qualification_id for c in candidates}
 if not set(passed.evidence_ids)&eligible:
  raise Waiting('Qualified prices for this fixture are no longer current; awaiting market revalidation',code='QUALIFIED_PRICES_EXPIRED')
 previous=latest_record(db,run,'PROGRAMMES_ALLOCATED')
 if previous and all(set(proposal['qualification_ids'])<=eligible for proposal in previous.details['proposals']):return previous
 proposals=[];refs=[];skipped=[]
 for key,config in PROGRAMMES.items():
  programme=db.scalar(select(m.Programme).where(m.Programme.key==key))
  if programme is None:skipped.append({'programme':key,'reason':'PROGRAMME_NOT_CONFIGURED'});continue
  start=at.replace(hour=0,minute=0,second=0,microsecond=0)
  used=db.scalar(select(func.count()).select_from(m.Ticket).where(m.Ticket.programme_id==programme.id,m.Ticket.created_at>=start,m.Ticket.created_at<start+timedelta(days=1))) or 0
  if used>=config['daily_cap']:skipped.append({'programme':key,'reason':'DAILY_EXPOSURE_LIMIT_REACHED'});continue
  options=[]
  for bookmaker in sorted(set(bookmakers.values())):
   selected=select_tickets([c for c in candidates if bookmakers[c.qualification_id]==bookmaker],key,limit=config['daily_cap']-used,draw_legs=2 if key=='draws' else None)
   for proposal in selected:
    group=[c for c in candidates if c.qualification_id in proposal['qualification_ids']]
    if not any(c.fixture_id==run.fixture_id for c in group):continue
    # Frechet lower bounds apply without assuming independent fixture outcomes.
    worst=Decimal(proposal['probability_lower_bound'])*Decimal(proposal['combined_odds'])-1
    if len(group)>1 and worst<=Decimal('.02'):continue
    proposal={**proposal,'correlation_status':'BOUNDED_WITHOUT_INDEPENDENCE' if len(group)>1 else 'NOT_APPLICABLE','paper_risk':{'unit_exposure':1,'worst_case_expected_return':str(worst),'dependency_policy':'FRECHET_LOWER_BOUND','daily_cap':config['daily_cap']}}
    options.append(proposal)
  options=options[:config['daily_cap']-used]
  if not options:continue
  identity='pipeline:'+run.id+':'+key+':'+hashlib.sha256(json.dumps(options,sort_keys=True,default=str).encode()).hexdigest()[:24]
  allocation=db.scalar(select(m.StrategyRun).where(m.StrategyRun.programme_key==key,m.StrategyRun.idempotency_key==identity))
  if allocation is None:
   allocation=m.StrategyRun(programme_key=key,idempotency_key=identity,status='COMPLETED',created_at=at,result={'mode':'PAPER','run_id':run.id,'fixture_id':run.fixture_id,'proposals':options});db.add(allocation);db.flush()
  refs.append(allocation.id)
  proposals.extend({'programme':key,**proposal} for proposal in options)
 if not proposals:
  raise Waiting('No programme proposal passes exposure, correlation, odds and daily-cap constraints',list(eligible&set(passed.evidence_ids)),
                state='NO_OPPORTUNITY',code='NO_ELIGIBLE_ALLOCATION',details={'candidate_count':len(candidates),'skipped_programmes':skipped})
 return receipt(db,run,'allocate','PROGRAMMES_ALLOCATED',refs,{'proposals':proposals,'skipped_programmes':skipped},at)


# 09 Prepare ---------------------------------------------------------------------------

def prepare(db,run,at):
 from app.modules.tickets.service import prepare_paper_ticket,TicketRejected
 allocation=latest_record(db,run,'PROGRAMMES_ALLOCATED')
 if allocation is None:raise Waiting('No validated programme allocation exists',code='ALLOCATION_REQUIRED')
 tickets=[];refs=[];summaries=[];rejected=[]
 for proposal in allocation.details['proposals']:
  programme=db.scalar(select(m.Programme).where(m.Programme.key==proposal['programme']))
  signature=set(proposal['qualification_ids'])
  ticket=None
  for candidate in db.scalars(select(m.Ticket).where(m.Ticket.programme_id==programme.id)):
   if {leg.qualification_id for leg in db.scalars(select(m.TicketLeg).where(m.TicketLeg.ticket_id==candidate.id))}==signature:ticket=candidate;break
  if ticket is None:
   try:result=prepare_paper_ticket(db,proposal['programme'],proposal['qualification_ids'],at=at)
   except TicketRejected as exc:
    rejected.append({'programme':proposal['programme'],'qualification_ids':proposal['qualification_ids'],'reason':str(exc)});continue
   ticket=db.get(m.Ticket,result['id']);ticket.created_at=at
  slip=db.scalar(select(m.Betslip).where(m.Betslip.ticket_id==ticket.id))
  tickets.append(ticket.id);refs.extend([ticket.id,slip.id])
  summaries.append({'ticket_id':ticket.id,'programme':proposal['programme'],'legs':len(signature),'type':'SINGLE' if len(signature)==1 else 'ACCUMULATOR',
                    'combined_odds':str(slip.combined_odds),'probability_lower_bound':proposal.get('probability_lower_bound'),'risk':proposal.get('paper_risk')})
 if not tickets:
  raise Waiting('No allocated proposal produced a valid paper ticket: '+', '.join(sorted({r['reason'] for r in rejected})),
                state='REJECTED',code='TICKETS_REJECTED',details={'rejected':rejected})
 return receipt(db,run,'prepare','PAPER_TICKETS_PREPARED',refs,{'ticket_ids':tickets,'tickets':summaries,'rejected':rejected,'allocation_record_id':allocation.id},at)


# 10 Verify ----------------------------------------------------------------------------

def verify(db,run,at):
 from app.modules.tickets.service import validate_leg,TicketRejected
 preparation=latest_record(db,run,'PAPER_TICKETS_PREPARED')
 if not preparation:raise Waiting('No prepared paper ticket exists',code='PREPARATION_REQUIRED')
 refs=[];verified=[];rejected=[]
 for ident in preparation.details['ticket_ids']:
  ticket=db.get(m.Ticket,ident);slip=db.scalar(select(m.Betslip).where(m.Betslip.ticket_id==ident))
  if not ticket or not ticket.status.startswith('PAPER') or not slip:raise Waiting('Paper ticket or betslip is missing',state='BLOCKED',code='BETSLIP_MISSING')
  legs=db.scalars(select(m.TicketLeg).where(m.TicketLeg.ticket_id==ticket.id)).all()
  if not legs or len({row.qualification_id for row in legs})!=len(legs):raise Waiting('Betslip contains missing or duplicated legs',state='BLOCKED',code='BETSLIP_LEGS_INVALID')
  expected=[];combined=Decimal('1');reason=None;expiry=None
  for leg in legs:
   try:item=validate_leg(db,leg.qualification_id,at)
   except TicketRejected as exc:reason=str(exc);break
   q=db.get(m.Qualification,leg.qualification_id)
   if q.gates.get('market_risk')!='PASS':raise Waiting('Betslip market-risk proof is missing',state='BLOCKED',code='RISK_PROOF_MISSING')
   quote=db.get(m.Odds,q.odds_id);fixture=db.get(m.Fixture,item['fixture_id'])
   leg_expiry=min(utc(quote.observed_at)+QUOTE_MAX_AGE,utc(fixture.kickoff_at))
   expiry=leg_expiry if expiry is None else min(expiry,leg_expiry)
   expected.append(item);combined*=Decimal(item['odds'])
  if reason:
   ticket.status='PAPER_REJECTED';slip.status='PAPER_REJECTED'
   rejected.append({'ticket_id':ticket.id,'betslip_id':slip.id,'reason':reason});continue
  actual={x['qualification_id']:x for x in slip.selections}
  for item in expected:
   stored=actual.get(item['qualification_id'],{})
   if any(stored.get(key)!=item[key] for key in ('fixture_id','market','outcome','bookmaker')) or Decimal(str(stored.get('odds',0)))!=Decimal(item['odds']):
    raise Waiting('Betslip market, provider or quoted price was altered',state='BLOCKED',code='BETSLIP_TAMPERED')
  if slip.bookmaker!={item['bookmaker'] for item in expected}.pop():raise Waiting('Betslip bookmaker mismatch',state='BLOCKED',code='BETSLIP_TAMPERED')
  if {x['qualification_id'] for x in slip.selections}!={x['qualification_id'] for x in expected} or abs(Decimal(str(slip.combined_odds))-combined)>Decimal('.00001'):
   raise Waiting('Betslip selections or combined odds do not match qualified ticket legs',state='BLOCKED',code='BETSLIP_TAMPERED')
  proof=db.scalar(select(m.TicketVerification).where(m.TicketVerification.ticket_id==ticket.id,m.TicketVerification.evidence['scope'].as_string()=='PAPER_BETSLIP'))
  if proof is None:
   proof=m.TicketVerification(ticket_id=ticket.id,status='PAPER_VERIFIED',reason_codes=[],verified_at=at,evidence={'scope':'PAPER_BETSLIP','betslip_id':slip.id,'qualification_ids':[x['qualification_id'] for x in expected],'run_id':run.id,'expires_at':expiry.isoformat(),'external_submission':False});db.add(proof);db.flush()
  ticket.status='PAPER_VERIFIED';slip.status='PAPER_VERIFIED';refs.extend([proof.id,slip.id])
  verified.append({'ticket_id':ticket.id,'betslip_id':slip.id,'verification_id':proof.id,'combined_odds':str(combined),'expires_at':(proof.evidence or {}).get('expires_at',expiry.isoformat())})
 if not verified:
  raise Waiting('Every prepared betslip was rejected on revalidation: '+', '.join(sorted({r['reason'] for r in rejected})),
                [r['betslip_id'] for r in rejected],state='REJECTED',code='BETSLIP_REJECTED',details={'rejected':rejected})
 return receipt(db,run,'verify','PAPER_BETSLIPS_VERIFIED',refs,{'ticket_ids':[v['ticket_id'] for v in verified],'betslips':verified,'rejected':rejected,
  'verification_scope':'PAPER_BETSLIP','external_booking_code':None,'external_submission':False},at)


# 11 Monitor ---------------------------------------------------------------------------

def monitor(db,run,at):
 """Runs for every fixture, qualified or not, alongside the rest of the pipeline."""
 from app.modules.markets.monitoring import inspect_market
 from app.modules.tickets.service import validate_leg,TicketRejected
 fixture=db.get(m.Fixture,run.fixture_id)
 if fixture is None:raise Waiting('No canonical fixture is linked to this run',code='FIXTURE_MISSING')
 upcoming=at<utc(fixture.kickoff_at)
 market=inspect_market(db,fixture.id,at=at)
 proof=latest_record(db,run,'PAPER_BETSLIPS_VERIFIED')
 alerts=[];notices=[];revalidate=set()
 status=(fixture.status or '').upper()
 if status in CANCELLED:notices.append('FIXTURE_'+status);revalidate.add('discover')
 if proof and upcoming:
  for ticket_id in proof.details['ticket_ids']:
   for leg in db.scalars(select(m.TicketLeg).where(m.TicketLeg.ticket_id==ticket_id)):
    try:validate_leg(db,leg.qualification_id,at)
    except TicketRejected as exc:alerts.append(str(exc))
    q=db.get(m.Qualification,leg.qualification_id);p=db.get(m.Prediction,q.prediction_id)
    if not model_approved(db.get(m.ModelVersion,p.model_id)):alerts.append('MODEL_APPROVAL_REVOKED')
    feature=db.get(m.Feature,p.feature_id);dossier=db.get(m.Research,feature.research_id) if feature else None
    if dossier is None or any(not authorized(db,db.get(m.Observation,ident).source_id) for ident in dossier.evidence_ids if db.get(m.Observation,ident)):
     alerts.append('RESEARCH_SOURCE_REVOKED')
    evidence=db.get(m.MarketEvidence,q.odds_id)
    if evidence is None or not authorized(db,evidence.source_id):alerts.append('PRICE_SOURCE_REVOKED')
  alerts.extend(item['reason'] for item in market['alerts'])
 if upcoming:
  # Revalidation trigger: an evaluation built on quotes that are no longer fresh must be redone.
  stage=db.scalar(select(m.PipelineStage).where(m.PipelineStage.run_id==run.id,m.PipelineStage.stage_key=='evaluate'))
  evaluation=latest_record(db,run,'MARKET_RISK_EVALUATED')
  if stage is not None and stage.status=='VERIFIED' and evaluation is not None and at-utc(evaluation.created_at)>QUOTE_MAX_AGE:revalidate.add('evaluate')
 alerts=sorted(set(alerts))
 details={'phase':'PRE_MATCH' if upcoming else 'POST_KICKOFF','scope':'INTERNAL_PAPER_RISK_MONITOR','check_interval_seconds':30,
          'subscriptions':['fixture_status','market_prices','source_authorization','model_approval']+(['paper_tickets'] if proof else []),
          'ticket_ids':proof.details['ticket_ids'] if proof else [],'alerts':alerts,'notices':notices,
          'market_alerts':sorted({item['reason'] for item in market['alerts']}) if upcoming else [],'revalidate':sorted(revalidate)}
 record=receipt(db,run,'monitor','CONTINUOUS_MONITOR',[fixture.id,*([proof.id] if proof else [])],details,at,status='ALERT' if alerts else 'PASS',period=int(at.timestamp())//600)
 marker='PIPELINE_MONITOR:'+run.id
 if alerts:
  for ticket_id in proof.details['ticket_ids']:
   ticket=db.get(m.Ticket,ticket_id);slip=db.scalar(select(m.Betslip).where(m.Betslip.ticket_id==ticket_id))
   ticket.status='PAPER_SUSPENDED'
   if slip:slip.status='PAPER_SUSPENDED'
  if db.scalar(select(m.Incident).where(m.Incident.status=='OPEN',m.Incident.message.like(marker+'%'))) is None:db.add(m.Incident(severity='HIGH',message=marker+' '+','.join(alerts)))
  raise Waiting('Continuous monitor risk alerts: '+', '.join(alerts),[record.id],state='BLOCKED',code='MONITOR_ALERT',details={'revalidate':sorted(revalidate)})
 for incident in db.scalars(select(m.Incident).where(m.Incident.status=='OPEN',m.Incident.message.like(marker+'%'))):incident.status='RESOLVED'
 return record


# 12 Reconcile -------------------------------------------------------------------------

def reconcile(db,run,at):
 """Starts when a verified final result exists, whether or not a selection ever qualified."""
 from app.modules.results.automation import reconcile_observation
 fixture=db.get(m.Fixture,run.fixture_id)
 if fixture is None:raise Waiting('No canonical fixture is linked to this run',code='FIXTURE_MISSING')
 kickoff=utc(fixture.kickoff_at)
 if at<kickoff:raise Waiting('Fixture has not started; waiting for a verified final result',code='AWAITING_KICKOFF')
 observations=db.scalars(select(m.Observation).where(m.Observation.fixture_id==fixture.id,m.Observation.payload['section'].as_string()=='official_result',m.Observation.observed_at<=at).order_by(m.Observation.observed_at)).all()
 for obs in observations:
  if authorized(db,obs.source_id):reconcile_observation(db,obs.id)
 result=db.scalar(select(m.Result).where(m.Result.fixture_id==fixture.id,m.Result.verified_at<=at).order_by(m.Result.version.desc()).limit(1))
 if result is None:
  if at>=kickoff+RESULT_WINDOW:raise Waiting('No verified final result within seven days of kickoff',state='INSUFFICIENT_DATA',code='RESULT_UNAVAILABLE')
  raise Waiting('No verified FINAL result is available',code='AWAITING_RESULT')
 evidence=db.scalars(select(m.ResultEvidence).where(m.ResultEvidence.result_id==result.id)).all()
 if not evidence or not any(authorized(db,e.source_id) for e in evidence):raise Waiting('Final-result provenance is missing or revoked',state='BLOCKED',code='RESULT_PROVENANCE_REVOKED')
 predictions={p.id:p for p in db.scalars(select(m.Prediction).where(m.Prediction.fixture_id==fixture.id))}
 settlements=db.scalars(select(m.Settlement).where(m.Settlement.result_id==result.id)).all()
 if set(predictions)!={s.prediction_id for s in settlements}:raise Waiting('Final result has not yet settled every forecast',code='SETTLEMENT_PENDING')
 counts={'WON':0,'LOST':0,'VOID':0,'PUSH':0,'UNRESOLVED':0}
 feedback=[]
 for s in settlements:
  counts[s.outcome]=counts.get(s.outcome,0)+1
  if s.outcome in ('WON','LOST'):
   p=float(predictions[s.prediction_id].probability);y=1 if s.outcome=='WON' else 0
   feedback.append({'prediction_id':s.prediction_id,'model_id':predictions[s.prediction_id].model_id,'probability':round(p,7),'label':y,
                    'brier':round((p-y)**2,7),'log_loss':round(-math.log(max(1e-12,p if y else 1-p)),7)})
 tickets=db.scalars(select(m.Ticket).join(m.TicketLeg,m.TicketLeg.ticket_id==m.Ticket.id).join(m.Qualification,m.Qualification.id==m.TicketLeg.qualification_id)
         .join(m.Prediction,m.Prediction.id==m.Qualification.prediction_id).where(m.Prediction.fixture_id==fixture.id)).unique().all()
 return receipt(db,run,'reconcile','VERIFIED_RESULT_RECONCILED',[result.id,*[s.id for s in settlements],*[e.observation_id for e in evidence]],
  {'result_id':result.id,'version':result.version,'settlements':len(settlements),'classifications':counts,
   'outcomes':{s.prediction_id:s.outcome for s in settlements},'ticket_ids':sorted(t.id for t in tickets),
   'qualified_path':bool(tickets),'model_feedback':sorted(feedback,key=lambda x:x['prediction_id'])},at)


OPERATIONS={'discover':discover,'acquire':acquire,'research':research,'analyse':analyse,'predict':predict,'evaluate':evaluate,'qualify':qualify,'allocate':allocate,'prepare':prepare,'verify':verify,'monitor':monitor,'reconcile':reconcile}
