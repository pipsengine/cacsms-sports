"""Actual operations for the twelve stages; all attestations reference persisted evidence."""
import hashlib,json,os,math
from collections import defaultdict
from datetime import datetime,timedelta,timezone
from decimal import Decimal
from sqlalchemy import select,func
from app.db import models as m
from app.modules.research.league import utc
from app.modules.research.service import SECTIONS,build_dossier
from app.modules.acquisition.service import build_feature_snapshot
from app.modules.prediction.prospective import infer_approved,REQUIRED_APPROVALS
from app.modules.prediction.service import FEATURE_NAMES

class Waiting(ValueError):
 def __init__(self,reason,evidence=None,state='WAITING_FOR_DATA'):
  super().__init__(reason);self.evidence=evidence or [];self.state=state


def receipt(db,run,key,kind,refs,details,at,status='PASS',period=None):
 identity=[run.id,key,kind,sorted(set(refs)),details,period]
 digest=hashlib.sha256(json.dumps(identity,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
 existing=db.scalar(select(m.StageRecord).where(m.StageRecord.operation_key==digest))
 if existing:return existing
 record=m.StageRecord(run_id=run.id,fixture_id=run.fixture_id,stage_key=key,kind=kind,operation_key=digest,
       status=status,evidence_ids=sorted(set(refs)),details=details,created_at=at)
 db.add(record);db.flush();return record


def authorized(db,source_id):
 source=db.get(m.Source,source_id)
 return source is not None and source.enabled and source.permission=='AUTHORIZED'


def data_of(obs):
 content=obs.payload.get('data',obs.payload.get('values',{}))
 if isinstance(content,dict) and content.get('section') and isinstance(content.get('data'),dict):content=content['data']
 return content


def discover(db,run,at):
 fixture=db.get(m.Fixture,run.fixture_id)
 if fixture is None:raise Waiting('No canonical fixture is linked to this run')
 if fixture.home_name.strip().casefold()==fixture.away_name.strip().casefold():raise Waiting('Fixture team identities conflict',state='BLOCKED')
 records=db.scalars(select(m.Observation).where(m.Observation.fixture_id==fixture.id)).all()
 refs=[o.id for o in records if authorized(db,o.source_id) and o.content_hash and utc(o.observed_at)<=at]
 if not refs:raise Waiting('Fixture has no currently authorized provenance')
 competition=db.get(m.Competition,fixture.competition_id)
 if not competition:raise Waiting('Fixture competition identity is missing',state='BLOCKED')
 return receipt(db,run,'discover','FIXTURE_IDENTIFIED',[fixture.id,*refs],{'competition_id':competition.id,'sport_id':competition.sport_id,'kickoff_at':fixture.kickoff_at.isoformat()},at)


def acquire(db,run,at):
 from app.modules.acquisition.jobs import feed_config,enqueue
 from app.modules.acquisition.service import ALLOWED_SECTIONS
 feeds=feed_config();jobs=[]
 for source in db.scalars(select(m.Source).where(m.Source.enabled.is_(True),m.Source.permission=='AUTHORIZED')):
  sections=feeds.get(source.id,{})
  if not isinstance(sections,dict):continue
  fixture=db.get(m.Fixture,run.fixture_id)
  for section in set(sections)&set(ALLOWED_SECTIONS):
   if utc(fixture.kickoff_at)<=at and section!='official_result':continue
   if utc(fixture.kickoff_at)>at and section=='official_result':continue
   result=enqueue(db,source.id,fixture.id,section,at.strftime('%Y%m%d%H') if section!='market_odds' else at.strftime('%Y%m%d%H%M')[:-1])
   if result['status'] in ('PENDING','RETRY_SCHEDULED'):jobs.append(result['id'])
 run.context={**(run.context or {}),'queued_job_ids':sorted(set(jobs))}
 observations=db.scalars(select(m.Observation).where(m.Observation.fixture_id==run.fixture_id,m.Observation.observed_at<=at)).all()
 refs=[o.id for o in observations if authorized(db,o.source_id) and o.content_hash]
 if not refs:raise Waiting('Authorized acquisition jobs are queued; awaiting actual observations',jobs)
 return receipt(db,run,'acquire','SOURCE_EVIDENCE_ACQUIRED',refs,{'observation_count':len(refs),'queued_job_ids':jobs,'capture_policy':'Structured feeds or independently reviewed browser evidence; no assumed vision verification'},at)



def canonical_content(value):
 if isinstance(value,bool) or value is None:return value
 if type(value) in (int,float):
  if not math.isfinite(value):raise Waiting('Research evidence contains a non-finite numeric value',state='BLOCKED')
  return float(value)
 if isinstance(value,list):return [canonical_content(item) for item in value]
 if isinstance(value,dict):return {key:canonical_content(item) for key,item in value.items()}
 return value


def research(db,run,at):
 fixture=db.get(m.Fixture,run.fixture_id)
 observations=db.scalars(select(m.Observation).where(m.Observation.fixture_id==fixture.id,m.Observation.observed_at<=at,
     m.Observation.observed_at<fixture.kickoff_at).order_by(m.Observation.observed_at.desc(),m.Observation.id)).all()
 valid=[o for o in observations if authorized(db,o.source_id) and o.content_hash]
 latest=db.scalar(select(m.Research).where(m.Research.fixture_id==fixture.id).order_by(m.Research.version.desc()).limit(1))
 available={o.id for o in valid}
 if latest and latest.status=='VERIFIED' and latest.evidence_ids and set(latest.evidence_ids)<=available and all(latest.sections.get(k,{}).get('status')=='VERIFIED' for k in SECTIONS) and not any(o.payload.get('section') in SECTIONS and utc(o.observed_at)>utc(latest.created_at) for o in valid):
  return receipt(db,run,'research','DOSSIER_VERIFIED',[latest.id,*latest.evidence_ids],{'dossier_id':latest.id,'version':latest.version,'verification':'EXISTING_INDEPENDENT_REVIEW'},at)
 try:policy=json.loads(os.getenv('SPORTS_RESEARCH_QUORUM_JSON') or '{}')
 except ValueError:raise Waiting('Research corroboration policy is invalid',state='BLOCKED')
 if not isinstance(policy,dict):raise Waiting('Research corroboration policy must be an object',state='BLOCKED')
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
  sections[section]={'status':'VERIFIED' if ids else 'PENDING','evidence_ids':ids,'details':{'method':'INDEPENDENT_REVIEW' if reviewed else 'CROSS_SOURCE_QUORUM','independence_groups':[g for g,_ in quorum] if quorum else []}}
  refs.extend(ids)
 if not refs:raise Waiting('Research requires independently reviewed evidence or agreement from two configured independent source groups')
 if latest and set(latest.evidence_ids)==set(refs) and latest.sections==sections:dossier=latest
 else:
  built=build_dossier(db,fixture.id,sections,sorted(set(refs)),at=at);dossier=db.get(m.Research,built['id'])
 missing=[k for k in SECTIONS if sections[k]['status']!='VERIFIED']
 if missing:raise Waiting('Research sections lack corroboration: '+', '.join(missing),[dossier.id])
 return receipt(db,run,'research','DOSSIER_VERIFIED',[dossier.id,*refs],{'dossier_id':dossier.id,'version':dossier.version,'verification':'INDEPENDENT_SOURCE_CORROBORATION'},at)


def analyse(db,run,at):
 dossier=db.scalar(select(m.Research).where(m.Research.fixture_id==run.fixture_id,m.Research.status=='VERIFIED').order_by(m.Research.version.desc()).limit(1))
 if not dossier:raise Waiting('A verified research dossier is required')
 numbers={}
 for section in ('recent_form','match_statistics'):
  for ident in dossier.sections.get(section,{}).get('evidence_ids',[]):
   obs=db.get(m.Observation,ident)
   if not obs or not authorized(db,obs.source_id):raise Waiting('Analysis evidence source has been revoked')
   content=data_of(obs)
   if isinstance(content,dict):
    for key in FEATURE_NAMES:
     if key in content:
      value=content[key]
      if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=10:raise Waiting('Invalid numeric research feature: '+key,state='BLOCKED')
      if key in numbers and numbers[key]!=float(value):raise Waiting('Conflicting numeric feature: '+key,state='BLOCKED')
      numbers[key]=float(value)
 if set(numbers)!=set(FEATURE_NAMES):raise Waiting('Verified research lacks the six required sport-specific numeric features')
 feature=db.scalar(select(m.Feature).where(m.Feature.research_id==dossier.id).order_by(m.Feature.cutoff_at.desc()).limit(1))
 if feature is None or feature.features.get('numeric_features')!=numbers:
  built=build_feature_snapshot(db,research_id=dossier.id,cutoff_at=at,required_sections=list(SECTIONS));feature=db.get(m.Feature,built['id'])
  feature.features={**feature.features,'numeric_features':numbers}
 return receipt(db,run,'analyse','FEATURES_MATERIALIZED',[feature.id,dossier.id,*dossier.evidence_ids],{'feature_id':feature.id,'cutoff_at':feature.cutoff_at.isoformat(),'feature_names':list(FEATURE_NAMES)},at)


def predict(db,run,at):
 latest=db.scalar(select(m.Research).where(m.Research.fixture_id==run.fixture_id,m.Research.status=='VERIFIED').order_by(m.Research.version.desc()).limit(1))
 report=infer_approved(db,db.get(m.Fixture,run.fixture_id),now=at,dossier_id=latest.id if latest else None)
 refs=report['created']+report['existing']
 if not refs:raise Waiting('; '.join(dict.fromkeys(report['blocked'])) or 'No approved inference artifact can produce a valid forecast')
 return receipt(db,run,'predict','FORECASTS_GENERATED',refs,{'prediction_ids':refs,'model_policy':'ACTIVE, approved, out-of-sample, calibrated and calibration-verified'},at)


def import_prices(db,fixture_id,at):
 observations=db.scalars(select(m.Observation).where(m.Observation.fixture_id==fixture_id,m.Observation.observed_at<=at).order_by(m.Observation.observed_at.desc(),m.Observation.id)).all()
 seen_sources=set()
 for obs in observations:
  if obs.payload.get('section')!='market_odds' or not authorized(db,obs.source_id) or obs.source_id in seen_sources:continue
  seen_sources.add(obs.source_id)
  prices=data_of(obs).get('prices',[]) if isinstance(data_of(obs),dict) else []
  if not isinstance(prices,list) or len(prices)>100:raise Waiting('Invalid market quote evidence',state='BLOCKED')
  for row in prices:
   try:
    stamp=datetime.fromisoformat(row['observed_at'].replace('Z','+00:00'));price=Decimal(str(row['decimal_odds']))
    if stamp.tzinfo is None or stamp>at or utc(obs.observed_at)<stamp or not price.is_finite() or not Decimal('1')<price<=1000:raise ValueError()
    if row['market_key']!='1X2' or row['outcome_key'] not in ('HOME','DRAW','AWAY') or not isinstance(row['bookmaker'],str) or not row['bookmaker']:raise ValueError()
   except (ValueError,TypeError,KeyError,ArithmeticError):raise Waiting('Invalid, future or unsupported source-backed price',state='BLOCKED')
   quote=db.scalar(select(m.Odds).where(m.Odds.fixture_id==fixture_id,m.Odds.bookmaker==row['bookmaker'],m.Odds.market_key==row['market_key'],m.Odds.outcome_key==row['outcome_key'],m.Odds.observed_at==stamp))
   if quote is None:
    quote=m.Odds(fixture_id=fixture_id,bookmaker=row['bookmaker'],market_key=row['market_key'],outcome_key=row['outcome_key'],decimal_odds=price,observed_at=stamp);db.add(quote);db.flush()
   elif Decimal(str(quote.decimal_odds))!=price:raise Waiting('Conflicting source quotes at the same timestamp',state='BLOCKED')
   if db.get(m.MarketEvidence,quote.id) is None:db.add(m.MarketEvidence(odds_id=quote.id,observation_id=obs.id,source_id=obs.source_id))
 db.flush()


def evaluate(db,run,at):
 import_prices(db,run.fixture_id,at)
 quotes=db.scalars(select(m.Odds).where(m.Odds.fixture_id==run.fixture_id).order_by(m.Odds.observed_at.desc(),m.Odds.id)).all()
 latest={}
 for quote in quotes:
  proof=db.get(m.MarketEvidence,quote.id)
  if proof and authorized(db,proof.source_id) and timedelta(0)<=at-utc(quote.observed_at)<=timedelta(minutes=15):latest.setdefault((quote.bookmaker,quote.market_key,quote.outcome_key),quote)
 forecast=db.scalar(select(m.StageRecord).where(m.StageRecord.run_id==run.id,m.StageRecord.kind=='FORECASTS_GENERATED').order_by(m.StageRecord.created_at.desc()).limit(1))
 predictions=db.scalars(select(m.Prediction).where(m.Prediction.fixture_id==run.fixture_id,m.Prediction.id.in_(forecast.evidence_ids if forecast else []))).all()
 pairs=[];refs=[]
 for prediction in predictions:
  for (book,market,outcome),quote in latest.items():
   if prediction.market_key!=market or prediction.outcome_key!=outcome:continue
   full=[latest.get((book,market,choice)) for choice in ('HOME','DRAW','AWAY')]
   if any(item is None for item in full):continue
   overround=sum(1/float(item.decimal_odds) for item in full)
   if not .90<=overround<=1.25:continue
   model=db.get(m.ModelVersion,prediction.model_id)
   if not model or model.status!='ACTIVE' or any(model.validation.get(k) is not True for k in REQUIRED_APPROVALS):continue
   pairs.append({'prediction_id':prediction.id,'odds_id':quote.id,'overround':overround,'market_risk':'PASS'})
   refs.extend([prediction.id,*[q.id for q in full],*[db.get(m.MarketEvidence,q.id).observation_id for q in full]])
 if not pairs:raise Waiting('No complete, source-backed, fresh 1X2 market passes probability/model and overround risk checks')
 return receipt(db,run,'evaluate','MARKET_RISK_EVALUATED',refs,{'pairs':pairs,'max_quote_age_seconds':900,'overround_range':[.90,1.25],'paper_exposure_only':True},at)


def qualify(db,run,at):
 from app.modules.markets.persistence import qualify_from_database
 evaluation=db.scalar(select(m.StageRecord).where(m.StageRecord.run_id==run.id,m.StageRecord.kind=='MARKET_RISK_EVALUATED').order_by(m.StageRecord.created_at.desc()).limit(1))
 if evaluation is None:raise Waiting('No market-risk evaluation exists')
 refs=[];rejections=[]
 for pair in evaluation.details['pairs']:
  previous=db.scalar(select(m.Qualification).where(m.Qualification.prediction_id==pair['prediction_id'],m.Qualification.odds_id==pair['odds_id']).order_by(m.Qualification.decided_at.desc()).limit(1))
  if previous is None:
   result=qualify_from_database(db,pair['prediction_id'],pair['odds_id'],now=at);previous=db.get(m.Qualification,result['id']);previous.decided_at=at
   previous.gates={**previous.gates,'market_risk':'PASS','risk_record_id':evaluation.id}
  if previous.decision=='QUALIFIED' and previous.gates.get('market_risk')=='PASS':refs.append(previous.id)
  else:rejections.extend(previous.gates.get('reason_codes',[]))
 if not refs:raise Waiting('Qualification rejected: '+', '.join(sorted(set(rejections))),state='BLOCKED')
 return receipt(db,run,'qualify','QUALIFICATIONS_PASSED',refs,{'qualification_ids':refs,'market_risk_record_id':evaluation.id},at)


def allocate(db,run,at):
 from app.modules.strategies.optimizer import Candidate,select_tickets,PROGRAMMES
 passed=db.scalar(select(m.StageRecord).where(m.StageRecord.run_id==run.id,m.StageRecord.kind=='QUALIFICATIONS_PASSED').order_by(m.StageRecord.created_at.desc()).limit(1))
 qualifications=db.scalars(select(m.Qualification).where(m.Qualification.decision=='QUALIFIED')).all()
 candidates=[];bookmakers={}
 for q in qualifications:
  if q.gates.get('market_risk')!='PASS':continue
  p=db.get(m.Prediction,q.prediction_id);price=db.get(m.Odds,q.odds_id);fixture=db.get(m.Fixture,p.fixture_id)
  if at>=utc(fixture.kickoff_at) or not timedelta(0)<=at-utc(price.observed_at)<=timedelta(minutes=15):continue
  model=db.get(m.ModelVersion,p.model_id);evidence=db.get(m.MarketEvidence,price.id)
  if not model or model.status!='ACTIVE' or any(model.validation.get(k) is not True for k in REQUIRED_APPROVALS):continue
  if evidence is None or not authorized(db,evidence.source_id):continue
  feature=db.get(m.Feature,p.feature_id);dossier=db.get(m.Research,feature.research_id) if feature else None
  current=db.scalar(select(m.Research).where(m.Research.fixture_id==fixture.id).order_by(m.Research.version.desc()).limit(1))
  if dossier is None or current is None or current.id!=dossier.id or dossier.status!='VERIFIED':continue
  observations=[db.get(m.Observation,ident) for ident in dossier.evidence_ids]
  if any(obs is None or not authorized(db,obs.source_id) for obs in observations):continue
  latest=db.scalar(select(m.Odds).where(m.Odds.fixture_id==fixture.id,m.Odds.bookmaker==price.bookmaker,m.Odds.market_key==price.market_key,m.Odds.outcome_key==price.outcome_key,m.Odds.observed_at<=at).order_by(m.Odds.observed_at.desc()).limit(1))
  if latest.id!=price.id:continue
  candidates.append(Candidate(q.id,fixture.id,Decimal(str(price.decimal_odds)),Decimal(str(p.probability)),p.market_key,p.outcome_key,fixture.kickoff_at.isoformat()))
  bookmakers[q.id]=price.bookmaker
 if passed is None or not set(passed.evidence_ids)&{c.qualification_id for c in candidates}:raise Waiting('No current qualified selection for this fixture passes allocation risk gates')
 previous=db.scalar(select(m.StageRecord).where(m.StageRecord.run_id==run.id,m.StageRecord.kind=='PROGRAMMES_ALLOCATED').order_by(m.StageRecord.created_at.desc()).limit(1))
 eligible={c.qualification_id for c in candidates}
 if previous and all(set(proposal['qualification_ids'])<=eligible for proposal in previous.details['proposals']):return previous
 proposals=[];refs=[]
 for key,config in PROGRAMMES.items():
  programme=db.scalar(select(m.Programme).where(m.Programme.key==key))
  if programme is None:continue
  start=at.replace(hour=0,minute=0,second=0,microsecond=0)
  used=db.scalar(select(func.count()).select_from(m.Ticket).where(m.Ticket.programme_id==programme.id,m.Ticket.created_at>=start,m.Ticket.created_at<start+timedelta(days=1))) or 0
  if used>=config['daily_cap']:continue
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
 if not proposals:raise Waiting('No programme proposal passes exposure, correlation, odds and daily-cap constraints')
 return receipt(db,run,'allocate','PROGRAMMES_ALLOCATED',refs,{'proposals':proposals},at)


def prepare(db,run,at):
 from app.modules.tickets.service import prepare_paper_ticket
 allocation=db.scalar(select(m.StageRecord).where(m.StageRecord.run_id==run.id,m.StageRecord.kind=='PROGRAMMES_ALLOCATED').order_by(m.StageRecord.created_at.desc()).limit(1))
 if allocation is None:raise Waiting('No validated programme allocation exists')
 tickets=[];refs=[]
 for proposal in allocation.details['proposals']:
  programme=db.scalar(select(m.Programme).where(m.Programme.key==proposal['programme']))
  existing=db.scalars(select(m.Ticket).where(m.Ticket.programme_id==programme.id)).all()
  signature=set(proposal['qualification_ids'])
  ticket=next((t for t in existing if {l.qualification_id for l in db.scalars(select(m.TicketLeg).where(m.TicketLeg.ticket_id==t.id))}==signature),None)
  if ticket is None:
   result=prepare_paper_ticket(db,proposal['programme'],proposal['qualification_ids'],at=at);ticket=db.get(m.Ticket,result['id']);ticket.created_at=at
  slip=db.scalar(select(m.Betslip).where(m.Betslip.ticket_id==ticket.id))
  tickets.append(ticket.id);refs.extend([ticket.id,slip.id])
 return receipt(db,run,'prepare','PAPER_TICKETS_PREPARED',refs,{'ticket_ids':tickets,'allocation_record_id':allocation.id},at)


def verify(db,run,at):
 from app.modules.tickets.service import validate_leg,TicketRejected
 preparation=db.scalar(select(m.StageRecord).where(m.StageRecord.run_id==run.id,m.StageRecord.kind=='PAPER_TICKETS_PREPARED').order_by(m.StageRecord.created_at.desc()).limit(1))
 if not preparation:raise Waiting('No prepared paper ticket exists')
 refs=[]
 for ident in preparation.details['ticket_ids']:
  ticket=db.get(m.Ticket,ident);slip=db.scalar(select(m.Betslip).where(m.Betslip.ticket_id==ident))
  if not ticket or not ticket.status.startswith('PAPER') or not slip:raise Waiting('Paper ticket or betslip is missing',state='BLOCKED')
  legs=db.scalars(select(m.TicketLeg).where(m.TicketLeg.ticket_id==ticket.id)).all()
  if not legs or len({row.qualification_id for row in legs})!=len(legs):raise Waiting('Betslip contains missing or duplicated legs',state='BLOCKED')
  expected=[];combined=Decimal('1')
  for leg in legs:
   try:item=validate_leg(db,leg.qualification_id,at)
   except TicketRejected as exc:raise Waiting(str(exc),state='BLOCKED')
   q=db.get(m.Qualification,leg.qualification_id)
   if q.gates.get('market_risk')!='PASS':raise Waiting('Betslip market-risk proof is missing',state='BLOCKED')
   expected.append(item);combined*=Decimal(item['odds'])
  actual={x['qualification_id']:x for x in slip.selections}
  for item in expected:
   stored=actual.get(item['qualification_id'],{})
   if any(stored.get(key)!=item[key] for key in ('fixture_id','market','outcome','bookmaker')) or Decimal(str(stored.get('odds',0)))!=Decimal(item['odds']):
    raise Waiting('Betslip market, provider or quoted price was altered',state='BLOCKED')
  if slip.bookmaker!={item['bookmaker'] for item in expected}.pop():raise Waiting('Betslip bookmaker mismatch',state='BLOCKED')
  if {x['qualification_id'] for x in slip.selections}!={x['qualification_id'] for x in expected} or abs(Decimal(str(slip.combined_odds))-combined)>Decimal('.00001'):
   raise Waiting('Betslip selections or combined odds do not match qualified ticket legs',state='BLOCKED')
  proof=db.scalar(select(m.TicketVerification).where(m.TicketVerification.ticket_id==ticket.id,m.TicketVerification.evidence['scope'].as_string()=='PAPER_BETSLIP'))
  if proof is None:
   proof=m.TicketVerification(ticket_id=ticket.id,status='PAPER_VERIFIED',reason_codes=[],verified_at=at,evidence={'scope':'PAPER_BETSLIP','betslip_id':slip.id,'qualification_ids':[x['qualification_id'] for x in expected],'run_id':run.id,'external_submission':False});db.add(proof);db.flush()
  ticket.status='PAPER_VERIFIED';slip.status='PAPER_VERIFIED';refs.extend([proof.id,slip.id])
 return receipt(db,run,'verify','PAPER_BETSLIPS_VERIFIED',refs,{'ticket_ids':preparation.details['ticket_ids'],'verification_scope':'PAPER_BETSLIP','external_booking_code':None,'external_submission':False},at)


def monitor(db,run,at):
 from app.modules.markets.monitoring import inspect_market
 from app.modules.tickets.service import validate_leg,TicketRejected
 fixture=db.get(m.Fixture,run.fixture_id);market=inspect_market(db,fixture.id,at=at)
 proof=db.scalar(select(m.StageRecord).where(m.StageRecord.run_id==run.id,m.StageRecord.kind=='PAPER_BETSLIPS_VERIFIED').order_by(m.StageRecord.created_at.desc()).limit(1))
 alerts=[]
 if proof is None:raise Waiting('Monitoring awaits verified paper betslips')
 if at<utc(fixture.kickoff_at):
  for ticket_id in proof.details['ticket_ids']:
   for leg in db.scalars(select(m.TicketLeg).where(m.TicketLeg.ticket_id==ticket_id)):
    try:validate_leg(db,leg.qualification_id,at)
    except TicketRejected as exc:alerts.append(str(exc))
    q=db.get(m.Qualification,leg.qualification_id);p=db.get(m.Prediction,q.prediction_id);model=db.get(m.ModelVersion,p.model_id)
    if not model or model.status!='ACTIVE' or any(model.validation.get(k) is not True for k in REQUIRED_APPROVALS):alerts.append('MODEL_APPROVAL_REVOKED')
    feature=db.get(m.Feature,p.feature_id);dossier=db.get(m.Research,feature.research_id) if feature else None
    if dossier is None or any(not authorized(db,db.get(m.Observation,ident).source_id) for ident in dossier.evidence_ids if db.get(m.Observation,ident)):
     alerts.append('RESEARCH_SOURCE_REVOKED')
    evidence=db.get(m.MarketEvidence,q.odds_id)
    if evidence is None or not authorized(db,evidence.source_id):alerts.append('PRICE_SOURCE_REVOKED')
  alerts.extend(item['reason'] for item in market['alerts'])
 record=receipt(db,run,'monitor','CONTINUOUS_PAPER_MONITOR',[proof.id],{'market':market,'alerts':sorted(set(alerts)),'checked_at':at.isoformat(),'scope':'INTERNAL_PAPER_RISK_MONITOR','next_check_seconds':30},at,status='ALERT' if alerts else 'PASS',period=int(at.timestamp())//30)
 if alerts:
  for ticket_id in proof.details['ticket_ids']:
   ticket=db.get(m.Ticket,ticket_id);slip=db.scalar(select(m.Betslip).where(m.Betslip.ticket_id==ticket_id))
   ticket.status='PAPER_SUSPENDED'
   if slip:slip.status='PAPER_SUSPENDED'
  marker='PIPELINE_MONITOR:'+run.id
  if db.scalar(select(m.Incident).where(m.Incident.status=='OPEN',m.Incident.message.like(marker+'%'))) is None:db.add(m.Incident(severity='HIGH',message=marker+' '+','.join(sorted(set(alerts)))))
  raise Waiting('Continuous monitor risk alerts: '+', '.join(sorted(set(alerts))),[record.id],state='BLOCKED')
 for incident in db.scalars(select(m.Incident).where(m.Incident.status=='OPEN',m.Incident.message.like('PIPELINE_MONITOR:'+run.id+'%'))):incident.status='RESOLVED'
 return record


def reconcile(db,run,at):
 from app.modules.results.automation import reconcile_observation
 fixture=db.get(m.Fixture,run.fixture_id)
 if at<utc(fixture.kickoff_at):raise Waiting('Fixture has not started; waiting for a verified final result')
 observations=db.scalars(select(m.Observation).where(m.Observation.fixture_id==fixture.id,m.Observation.payload['section'].as_string()=='official_result',m.Observation.observed_at<=at).order_by(m.Observation.observed_at)).all()
 for obs in observations:
  if authorized(db,obs.source_id):reconcile_observation(db,obs.id)
 result=db.scalar(select(m.Result).where(m.Result.fixture_id==fixture.id,m.Result.verified_at<=at).order_by(m.Result.version.desc()).limit(1))
 if result is None:raise Waiting('No verified FINAL result is available')
 evidence=db.scalars(select(m.ResultEvidence).where(m.ResultEvidence.result_id==result.id)).all()
 if not evidence or not any(authorized(db,e.source_id) for e in evidence):raise Waiting('Final-result provenance is missing or revoked',state='BLOCKED')
 predictions=db.scalars(select(m.Prediction).where(m.Prediction.fixture_id==fixture.id)).all()
 settlements=db.scalars(select(m.Settlement).where(m.Settlement.result_id==result.id)).all()
 if predictions and ({p.id for p in predictions}!={s.prediction_id for s in settlements} or any(s.outcome=='UNRESOLVED' for s in settlements)):
  raise Waiting('Final result cannot resolve every forecast market yet')
 return receipt(db,run,'reconcile','VERIFIED_RESULT_RECONCILED',[result.id,*[s.id for s in settlements],*[e.observation_id for e in evidence]],{'result_id':result.id,'version':result.version,'settlements':len(settlements),'outcomes':{s.prediction_id:s.outcome for s in settlements}},at)

OPERATIONS={'discover':discover,'acquire':acquire,'research':research,'analyse':analyse,'predict':predict,'evaluate':evaluate,'qualify':qualify,'allocate':allocate,'prepare':prepare,'verify':verify,'monitor':monitor,'reconcile':reconcile}
