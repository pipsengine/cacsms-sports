"""Multi-market football model: independent Poisson goals from the verified pre-match rates.

One score distribution prices many markets (1X2, double chance, totals, BTTS, odd/even, team totals,
exact score). Each market OUTCOME is validated separately on corroborated history (features from earlier
matches only, chronological 70/30 split) and is approved only if, out of sample, it beats the train-set
base-rate forecast on Brier AND log-loss and its calibration error is within SPORTS_MODEL_MAX_ECE.
Unapproved outcomes are never published, so the scanner reports them as UNSUPPORTED.
"""
import math
from datetime import datetime,timedelta,timezone
from sqlalchemy import select
from app.db import models as m
from app.modules.research.league import utc

MODEL_TYPE='poisson_market'
NAME='Autonomous Poisson market model (football)'
MAX_GOALS=10
TOTAL_LINES=(0.5,1.5,2.5,3.5,4.5,5.5)
TEAM_LINES=(0.5,1.5,2.5)
SCORES=[(h,a) for h in range(4) for a in range(4)]
MIN_HOLDOUT=100
REQUIRED=('approved','out_of_sample','calibrated','calibration_verified')


def model_type(model):
 v=model.validation if model is not None and isinstance(model.validation,dict) else {}
 return v.get('model_type') or 'logistic'


def line_key(prefix,line):return f'{prefix}_{format(line,"g")}'


def settled_outcomes(hg,ag):
 """WON/LOST for every market this model prices (also used as the corroborated result payload)."""
 w=lambda c:'WON' if c else 'LOST';total=hg+ag;out={}
 out['1X2']={'HOME':w(hg>ag),'DRAW':w(hg==ag),'AWAY':w(hg<ag)}
 out['DC']={'1X':w(hg>=ag),'X2':w(hg<=ag),'12':w(hg!=ag)}
 for line in TOTAL_LINES:out[line_key('OU',line)]={'OVER':w(total>line),'UNDER':w(total<line)}
 for line in TEAM_LINES:
  out[line_key('HOME_OU',line)]={'OVER':w(hg>line),'UNDER':w(hg<line)}
  out[line_key('AWAY_OU',line)]={'OVER':w(ag>line),'UNDER':w(ag<line)}
 out['BTTS']={'YES':w(hg>0 and ag>0),'NO':w(not(hg>0 and ag>0))}
 out['ODD_EVEN']={'ODD':w(total%2==1),'EVEN':w(total%2==0)}
 out['CS']={f'{h}-{a}':w((hg,ag)==(h,a)) for h,a in SCORES}
 return out


def raw_rates(f):
 return (f['home_scoring_rate']+f['away_conceding_rate'])/2,(f['away_scoring_rate']+f['home_conceding_rate'])/2


def expected_goals(f,params=None):
 """Expected goals, shrunk toward the training league means when fitted parameters are supplied."""
 home,away=raw_rates(f)
 if params and params.get('shrink'):
  sh=params['shrink']
  home=sh['home']['mean']+sh['home']['weight']*(home-sh['home']['raw_mean'])
  away=sh['away']['mean']+sh['away']['weight']*(away-sh['away']['raw_mean'])
 return max(.05,home),max(.05,away)


def fit_shrink(train):
 """Per side, choose the weight on recent form (0..1) that maximises the Poisson likelihood of training goals."""
 out={}
 for side,idx in (('home',0),('away',1)):
  raw=[raw_rates(f)[idx] for f,_,_ in train];goals=[(hg,ag)[idx] for _,hg,ag in train]
  mean=sum(goals)/len(goals);raw_mean=sum(raw)/len(raw)
  def nll(w):return sum((lam:=max(.05,mean+w*(r-raw_mean)))-g*math.log(lam) for r,g in zip(raw,goals))
  weight=min((i/20 for i in range(21)),key=nll)
  out[side]={'mean':round(mean,6),'raw_mean':round(raw_mean,6),'weight':weight}
 return out


def _logit(p):p=min(1-1e-6,max(1e-6,p));return math.log(p/(1-p))
def _sigmoid(z):return 1/(1+math.exp(-z)) if z>=0 else math.exp(z)/(1+math.exp(z))


def fit_platt(pairs,iterations=30,ridge=1e-3):
 """Two-parameter logistic recalibration p' = sigmoid(a*logit(p)+b), fitted by Newton steps on training pairs."""
 a,b=1.0,0.0
 for _ in range(iterations):
  ga=gb=haa=hab=hbb=0.0
  for p,y in pairs:
   x=_logit(p);q=_sigmoid(a*x+b);r=q-y;w=q*(1-q)
   ga+=r*x;gb+=r;haa+=w*x*x;hab+=w*x;hbb+=w
  ga+=ridge*(a-1);gb+=ridge*b;haa+=ridge;hbb+=ridge
  det=haa*hbb-hab*hab
  if abs(det)<1e-12:break
  da=(hbb*ga-hab*gb)/det;db=(haa*gb-hab*ga)/det
  a,b=a-da,b-db
  if abs(da)<1e-7 and abs(db)<1e-7:break
 return [round(a,6),round(b,6)]


def groups():
 """Mutually exclusive, exhaustive outcome groups (re-normalised after calibration)."""
 out={'1X2':('HOME','DRAW','AWAY'),'BTTS':('YES','NO'),'ODD_EVEN':('ODD','EVEN')}
 for line in TOTAL_LINES:out[line_key('OU',line)]=('OVER','UNDER')
 for line in TEAM_LINES:out[line_key('HOME_OU',line)]=('OVER','UNDER');out[line_key('AWAY_OU',line)]=('OVER','UNDER')
 return out


def calibrated(raw,platt):
 """Apply per-outcome recalibration, keep groups coherent, derive double chance from the calibrated 1X2."""
 if not platt:return raw
 out=dict(raw)
 for market,outcomes in groups().items():
  vals=[_sigmoid(platt[f'{market}|{o}'][0]*_logit(raw[(market,o)])+platt[f'{market}|{o}'][1]) if f'{market}|{o}' in platt else raw[(market,o)] for o in outcomes]
  total=sum(vals) or 1
  for o,v in zip(outcomes,vals):out[(market,o)]=v/total
 for h,a in SCORES:
  key=f'CS|{h}-{a}'
  if key in platt:out[('CS',f'{h}-{a}')]=_sigmoid(platt[key][0]*_logit(raw[('CS',f'{h}-{a}')])+platt[key][1])
 home,draw,away=out[('1X2','HOME')],out[('1X2','DRAW')],out[('1X2','AWAY')]
 out[('DC','1X')],out[('DC','X2')],out[('DC','12')]=home+draw,draw+away,home+away
 return out


def probabilities(f,params=None):
 """Probability of every priced (market, outcome) from the six verified pre-match features (+ fitted parameters)."""
 lh,la=expected_goals(f,params)
 raw=_grid_probabilities(lh,la)
 return calibrated(raw,(params or {}).get('platt'))


def _grid_probabilities(lh,la):
 ph=[math.exp(-lh)*lh**k/math.factorial(k) for k in range(MAX_GOALS+1)]
 pa=[math.exp(-la)*la**k/math.factorial(k) for k in range(MAX_GOALS+1)]
 norm=sum(ph)*sum(pa)
 grid={(i,j):ph[i]*pa[j]/norm for i in range(MAX_GOALS+1) for j in range(MAX_GOALS+1)}
 out={}
 for (i,j),p in grid.items():
  for market,outcomes in settled_outcomes(i,j).items():
   for outcome,state in outcomes.items():
    if state=='WON':out[(market,outcome)]=out.get((market,outcome),0)+p
 for market,outcomes in settled_outcomes(0,0).items():
  for outcome in outcomes:out.setdefault((market,outcome),0.0)
 return out


def calibration_error(pairs):
 bins=[[] for _ in range(5)]
 for p,y in pairs:bins[min(4,int(p*5))].append((p,y))
 total=sum(len(b) for b in bins)
 return sum(len(b)*abs(sum(p for p,_ in b)/len(b)-sum(y for _,y in b)/len(b)) for b in bins if b)/total if total else None


def scores(pairs,eps=1e-12):
 n=len(pairs)
 return {'brier':round(sum((p-y)**2 for p,y in pairs)/n,6),'log_loss':round(-sum(y*math.log(max(eps,min(1-eps,p)))+(1-y)*math.log(max(eps,min(1-eps,1-p))) for p,y in pairs)/n,6),'sample_size':n}


def validate(rows,max_ece):
 """rows: chronological (features, hg, ag). Returns per-outcome validation keyed 'MARKET|OUTCOME'."""
 split=int(len(rows)*.7);train,test=rows[:split],rows[split:]
 results={}
 if len(test)<MIN_HOLDOUT:return results,len(train),len(test),{}
 labels=lambda hg,ag:{(mk,oc):1 if st=='WON' else 0 for mk,ocs in settled_outcomes(hg,ag).items() for oc,st in ocs.items()}
 train_labels=[labels(hg,ag) for _,hg,ag in train];test_labels=[labels(hg,ag) for _,hg,ag in test]
 # All parameters are fitted on the training (earlier) matches only; the later holdout judges them.
 params={'shrink':fit_shrink(train)}
 train_raw=[probabilities(f,params) for f,_,_ in train]
 params['platt']={'|'.join(key):fit_platt([(p[key],l[key]) for p,l in zip(train_raw,train_labels)]) for key in train_labels[0] if key[0]!='DC'}
 test_probs=[probabilities(f,params) for f,_,_ in test]
 for key in test_labels[0]:
  rate=sum(l[key] for l in train_labels)/len(train_labels)
  pairs=[(min(1-1e-6,max(1e-6,p[key])),l[key]) for p,l in zip(test_probs,test_labels)]
  model,base=scores(pairs),scores([(min(1-1e-6,max(1e-6,rate)),l[key]) for l in test_labels])
  ece=calibration_error(pairs);reasons=[]
  if not 0<rate<1:reasons.append('OUTCOME_NEVER_OR_ALWAYS_OCCURS_IN_TRAINING')
  if not (model['brier']<base['brier'] and model['log_loss']<base['log_loss']):reasons.append('DOES_NOT_BEAT_BASELINE_OUT_OF_SAMPLE')
  if ece is None or ece>max_ece:reasons.append('CALIBRATION_ERROR_TOO_HIGH')
  results['|'.join(key)]={'approved':not reasons,'reasons':reasons,'holdout':model,'baseline':base,'calibration_error':round(ece,6) if ece is not None else None,
                          'skill':round(1-model['brier']/base['brier'],6) if base['brier'] else None,'train_rate':round(rate,6)}
 return results,len(train),len(test),params


def history(db,competition_id,at):
 """Chronological leakage-safe (features, hg, ag, fixture_id) from corroborated results."""
 from app.modules.research.league import verified_matches
 from app.modules.autonomy.open_intelligence import features_for
 matches=verified_matches(db,competition_id,at)
 rows=sorted((dict(date=utc(g['kickoff']).date().isoformat(),home=g['home_id'],away=g['away_id'],hg=g['home_score'],ag=g['away_score'],finished=True) for g in matches),key=lambda r:r['date'])
 out=[]
 for g in sorted(matches,key=lambda g:utc(g['kickoff'])):
  built=features_for(rows,g['home_id'],g['away_id'],(utc(g['kickoff']).date()-timedelta(days=1)).isoformat())
  if built:out.append((built[0],g['home_score'],g['away_score'],g['id']))
 return out


def train(db,sport_id,competition_id,at=None):
 """Validate every outcome; activate the model (retiring older market models) only if at least one outcome passes."""
 import os
 at=at or datetime.now(timezone.utc)
 try:max_ece=float(os.getenv('SPORTS_MODEL_MAX_ECE','0.08'))
 except ValueError:max_ece=0.08
 rows=history(db,competition_id,at)
 markets,n_train,n_test,params=validate([(f,hg,ag) for f,hg,ag,_ in rows],max_ece)
 approved=[k for k,v in markets.items() if v['approved']]
 from app.modules.prediction.service import FEATURE_NAMES
 validation={'model_type':MODEL_TYPE,'feature_names':list(FEATURE_NAMES),'method':'Independent Poisson goals from verified pre-match rates, shrunk to league means; per-outcome Platt recalibration (train split only)',
             'training_count':n_train,'holdout_count':n_test,'parameters':params,'max_calibration_error':max_ece,'markets':markets,'approved_outcomes':len(approved),
             'validated_at':at.isoformat()}
 if approved:validation.update({k:True for k in REQUIRED})
 model=m.ModelVersion(sport_id=sport_id,name=NAME,version=at.strftime('%Y%m%d.%H%M%S'),status='ACTIVE' if approved else 'CHALLENGER',validation=validation)
 db.add(model);db.flush()
 if approved:
  for old in db.scalars(select(m.ModelVersion).where(m.ModelVersion.sport_id==sport_id,m.ModelVersion.status=='ACTIVE',m.ModelVersion.id!=model.id)):
   if model_type(old)==MODEL_TYPE:old.status='RETIRED'
 db.add(m.AuditEvent(actor='autonomous-model-governance',action='model.market_validation',correlation_id=model.id,
                     payload={'status':model.status,'approved_outcomes':approved,'rejected':{k:v['reasons'] for k,v in markets.items() if not v['approved']},
                              'holdout_count':n_test,'max_calibration_error':max_ece}))
 return {'model_id':model.id,'status':model.status,'approved_outcomes':len(approved),'validated_outcomes':len(markets),'holdout':n_test}


def active_model(db,sport_id):
 for model in db.scalars(select(m.ModelVersion).where(m.ModelVersion.sport_id==sport_id,m.ModelVersion.status=='ACTIVE')):
  v=model.validation or {}
  if model_type(model)==MODEL_TYPE and all(v.get(k) is True for k in REQUIRED):return model
 return None


def infer(db,fixture,dossier_id=None,now=None):
 """Publish probabilities for every APPROVED outcome of the active market model (idempotent)."""
 from app.modules.prediction.prospective import eligible
 now=now or datetime.now(timezone.utc)
 report={'created':[],'existing':[],'blocked':[]}
 model=active_model(db,fixture.sport_id)
 if model is None:report['blocked'].append('No validated market model');return report
 query=select(m.Research).where(m.Research.fixture_id==fixture.id,m.Research.status=='VERIFIED')
 if dossier_id:query=query.where(m.Research.id==dossier_id)
 for dossier in db.scalars(query):
  for feature in db.scalars(select(m.Feature).where(m.Feature.research_id==dossier.id)):
   ok,reason=eligible(model,feature,dossier,fixture,now)
   if not ok:report['blocked'].append(reason);continue
   params=model.validation.get('parameters') or {}
   f=feature.features['numeric_features'];probs=probabilities(f,params);lh,la=expected_goals(f,params)
   for key,v in (model.validation.get('markets') or {}).items():
    if not v.get('approved'):continue
    market,outcome=key.split('|',1)
    prior=db.scalar(select(m.Prediction).where(m.Prediction.fixture_id==fixture.id,m.Prediction.feature_id==feature.id,m.Prediction.model_id==model.id,
                                               m.Prediction.market_key==market,m.Prediction.outcome_key==outcome))
    if prior:report['existing'].append(prior.id);continue
    p=min(.9999,max(.0001,probs[(market,outcome)]));n=int(v['holdout']['sample_size']);ece=float(v['calibration_error'] or 0)
    width=1.96*math.sqrt(p*(1-p)/n)+ece
    details={'model_type':MODEL_TYPE,'interval':{'lower':round(max(0.0,p-width),6),'upper':round(min(1.0,p+width),6),'level':.95,'method':'HOLDOUT_BINOMIAL_PLUS_CALIBRATION_ERROR',
             'holdout_sample_size':n,'calibration_error':ece},'holdout_brier':v['holdout']['brier'],'baseline_brier':v['baseline']['brier'],'skill':v['skill'],
             'expected_goals':{'home':round(lh,4),'away':round(la,4)}}
    prediction=m.Prediction(fixture_id=fixture.id,feature_id=feature.id,model_id=model.id,market_key=market,outcome_key=outcome,probability=p,predicted_at=now,details=details)
    db.add(prediction);db.flush();report['created'].append(prediction.id)
 return report
