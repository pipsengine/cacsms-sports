"""Qualified Opportunities (adapted from the cacsms-qualified module onto canonical qualification decisions).

The module's own tables/scheduler are not used: opportunities ARE qualification.decisions rows with decision
QUALIFIED (produced by the autonomous qualification step / pipeline Qualify stage). Its policy thresholds
(minimum probability, minimum EV) are applied as opportunity filters on top of the qualification gates.
Evidence and rationale are built only from stored gates, research sections, sources and model validation.
"""
from sqlalchemy import select
from app.db import models as m
from app.modules.qualification import autonomous as aq

SECTION_LABEL={'standings':'league standings','recent_form':'team form','head_to_head':'head-to-head','match_statistics':'scoring/conceding trends',
               'team_news':'team news','lineups':'lineups','injuries':'injuries'}


def opportunities(db,only_qualified=True,min_probability=None,min_ev=None,search=None,sport=None,country=None,competition=None,category=None,at=None):
 at=at or aq._now()
 rows=[aq.decision_dict(db,*r) for r in aq._rows(db,'QUALIFIED' if only_qualified else 'ALL',search,sport,country,competition,category)]
 if not only_qualified:rows+=aq.pending_rows(db,at,search,sport,country,competition,category)
 if min_probability is not None:rows=[r for r in rows if r['probability'] is not None and r['probability']>=min_probability]
 # EV thresholds apply to priced rows; pending rows (no price) are kept only when not restricted to qualified.
 if min_ev is not None:rows=[r for r in rows if r['expected_value'] is None and r['decision']=='PENDING' or r['expected_value'] is not None and r['expected_value']>=min_ev]
 return rows


def _sections(dossier):
 out=[]
 for key,label in SECTION_LABEL.items():
  entry=(dossier.sections or {}).get(key,{}) if dossier else {}
  out.append({'key':key,'name':label,'status':entry.get('status','MISSING'),'method':(entry.get('details') or {}).get('method'),'evidence':len(entry.get('evidence_ids') or [])})
 return out


def rationale(item,sections,model_info):
 verified=[s['name'] for s in sections if s['status']=='VERIFIED']
 gates=item['gates'];failed=[aq.GATE_NAMES[g] for g in aq.GATES if gates.get(g)=='FAIL']
 parts=[f"verified research ({', '.join(verified)})" if verified else 'no verified research',
        f"approved calibrated model ({model_info['name']}, holdout Brier {model_info['holdout_brier']})" if model_info else 'no approved model']
 if item['decision']=='PENDING':
  return {'status':'PENDING','text':'Awaiting a source-backed price: '+'; '.join(parts)+'. Expected value, freshness and risk cannot be assessed, so it cannot qualify yet.'}
 age=None
 if item.get('odds_observed_at') and item.get('decided_at'):
  from app.modules.research.league import utc
  age=round((utc(item['decided_at'])-utc(item['odds_observed_at'])).total_seconds()/60,1)
 parts+= [f"odds {'fresh' if gates.get('odds_freshness')=='PASS' else 'stale'} ({age} min old at decision)" if age is not None else 'odds age unknown',
          f"expected value {item['expected_value']:+.1f}%" if item['expected_value'] is not None else 'no expected value',
          f"lower-bound EV {item['conservative_ev']:+.1f}%" if item['conservative_ev'] is not None else 'no lower bound',
          'market risk within policy' if gates.get('market_risk')=='PASS' else 'market risk outside policy']
 if item['decision']=='QUALIFIED':return {'status':'QUALIFIED','text':'Passes all quality gates: '+'; '.join(parts)+'.'}
 return {'status':'REJECTED','text':'Failed: '+', '.join(failed or item['reason_codes'])+'. Context: '+'; '.join(parts)+'.'}


def evidence(db,opportunity_id,at=None):
 at=at or aq._now()
 if opportunity_id.startswith('pending:'):
  item=next((r for r in aq.pending_rows(db,at) if r['id']==opportunity_id),None)
  if item is None:raise LookupError('Opportunity not found')
  prediction=db.get(m.Prediction,opportunity_id.split(':',1)[1])
 else:
  rows=[r for r in aq._rows(db,'ALL') if r[0].id==opportunity_id]
  if not rows:raise LookupError('Opportunity not found')
  item=aq.decision_dict(db,*rows[0]);prediction=rows[0][1]
 fixture=db.get(m.Fixture,item['fixture_id'])
 feature=db.get(m.Feature,prediction.feature_id);dossier=db.get(m.Research,feature.research_id) if feature else None
 model=db.get(m.ModelVersion,prediction.model_id);v=model.validation if model and isinstance(model.validation,dict) else {}
 market_v=((v.get('markets') or {}).get(f'{prediction.market_key}|{prediction.outcome_key}') or {})
 model_info={'name':f'{model.name} {model.version}','status':model.status,'holdout_brier':market_v.get('holdout',{}).get('brier') or (v.get('holdout_metrics') or {}).get('brier'),
             'baseline_brier':market_v.get('baseline',{}).get('brier') or (v.get('baseline_metrics') or {}).get('brier'),'calibration_error':market_v.get('calibration_error') or v.get('calibration_error'),
             'skill':market_v.get('skill')} if model else None
 sources=sorted({db.get(m.Source,o.source_id).name for o in db.scalars(select(m.Observation).where(m.Observation.id.in_(list(dossier.evidence_ids or [])))) if db.get(m.Source,o.source_id)}) if dossier else []
 sections=_sections(dossier)
 numeric=(feature.features or {}).get('numeric_features') if feature else None
 return {**item,'matchday':fixture.matchday,'research':{'dossier_id':dossier.id if dossier else None,'status':dossier.status if dossier else None,'sections':sections,'sources':sources,
         'evidence_items':len(dossier.evidence_ids or []) if dossier else 0},'features':numeric,'model':model_info,'rationale':rationale(item,sections,model_info),'mode':'PAPER'}
