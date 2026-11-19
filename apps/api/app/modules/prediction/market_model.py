"""Multi-market football model: independent Poisson goals from the verified pre-match rates.

One score distribution prices many markets (1X2, double chance, totals, BTTS, odd/even, team totals,
exact score). Each market OUTCOME is validated separately on corroborated history (features from earlier
matches only, chronological 70/30 split) and is approved only if, out of sample, it beats the train-set
base-rate forecast on Brier AND log-loss and its calibration error is within SPORTS_MODEL_MAX_ECE.
Unapproved outcomes are never published, so the scanner reports them as UNSUPPORTED.
Binary markets the Poisson grid prices poorly (BTTS, match totals, odd/even) may use a direct ridge logistic model
instead; that choice is made on an inner split of the training matches only, never by looking at the holdout.
"""
import math
from functools import lru_cache
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
 out=calibrated(raw,(params or {}).get('platt'))
 return apply_direct(out,f,params) if (params or {}).get('direct') else out


# Direct per-market models ------------------------------------------------------------------
# Binary markets the independent-Poisson grid prices poorly (both-teams-to-score, match totals, odd/even) may instead
# use a ridge logistic model on the same verified features. The choice and the ridge strength are made on an inner
# chronological split of the TRAINING matches only; the outer holdout still judges the result once, with the same gates.
DIRECT_MARKETS={'BTTS':('YES','NO'),'ODD_EVEN':('ODD','EVEN'),**{line_key('OU',line):('OVER','UNDER') for line in TOTAL_LINES}}
RIDGES=(1.0,3.0,10.0,30.0,100.0)
FEATURE_KEYS=('home_form','away_form','home_scoring_rate','away_scoring_rate','home_conceding_rate','away_conceding_rate')


def direct_features(f,params):
 lh,la=expected_goals(f,params)
 return [math.log(lh),math.log(la),math.log(lh+la),*(float(f[k]) for k in FEATURE_KEYS)]


def _solve(a,b):
 """Gaussian elimination with partial pivoting for the small Newton systems below."""
 n=len(b);a=[row[:]+[v] for row,v in zip(a,b)]
 for c in range(n):
  p=max(range(c,n),key=lambda r:abs(a[r][c]))
  if abs(a[p][c])<1e-12:raise ValueError('SINGULAR_SYSTEM')
  a[c],a[p]=a[p],a[c]
  for r in range(c+1,n):
   k=a[r][c]/a[c][c]
   for j in range(c,n+1):a[r][j]-=k*a[c][j]
 x=[0.0]*n
 for r in range(n-1,-1,-1):x[r]=(a[r][n]-sum(a[r][j]*x[j] for j in range(r+1,n)))/a[r][r]
 return x


def fit_logistic(rows,labels,ridge,iterations=25):
 """Ridge logistic regression on standardised features (intercept unpenalised), fitted by Newton steps."""
 d=len(rows[0]);mu=[sum(r[i] for r in rows)/len(rows) for i in range(d)]
 # A constant feature carries no information; scale 1 keeps it at z=0 (and survives rounding).
 sd=[s if (s:=(sum((r[i]-mu[i])**2 for r in rows)/len(rows))**.5)>1e-6 else 1.0 for i in range(d)]
 z=[[1.0,*((r[i]-mu[i])/sd[i] for i in range(d))] for r in rows];w=[0.0]*(d+1)
 for _ in range(iterations):
  grad=[0.0]*(d+1);hess=[[0.0]*(d+1) for _ in range(d+1)]
  for x,y in zip(z,labels):
   p=_sigmoid(sum(a*b for a,b in zip(w,x)));q=p*(1-p)
   for i in range(d+1):
    grad[i]+=(p-y)*x[i]
    for j in range(i,d+1):hess[i][j]+=q*x[i]*x[j]
  for i in range(d+1):
   for j in range(i):hess[i][j]=hess[j][i]
   if i:grad[i]+=ridge*w[i];hess[i][i]+=ridge
  step=_solve(hess,grad);w=[a-b for a,b in zip(w,step)]
  if max(abs(s) for s in step)<1e-8:break
 return {'weights':[round(v,8) for v in w],'mean':[round(v,8) for v in mu],'scale':[round(v,8) for v in sd],'ridge':ridge}


def logistic_probability(model,x):
 z=[1.0,*((v-m_)/s for v,m_,s in zip(x,model['mean'],model['scale']))]
 return _sigmoid(sum(a*b for a,b in zip(model['weights'],z)))


def apply_direct(out,f,params):
 out=dict(out);x=direct_features(f,params)
 for market,model in params['direct'].items():
  yes,no=DIRECT_MARKETS[market];p=min(1-1e-6,max(1e-6,logistic_probability(model,x)))
  out[(market,yes)],out[(market,no)]=p,1-p
 # Keep match totals coherent: P(over a higher line) never exceeds P(over a lower line).
 previous=1.0
 for line in TOTAL_LINES:
  key=line_key('OU',line);over=min(out[(key,'OVER')],previous);previous=over
  out[(key,'OVER')],out[(key,'UNDER')]=over,1-over
 return out


def poisson_params(train,train_labels):
 """Shrinkage and per-outcome Platt recalibration, fitted on the given (training) matches only."""
 params={'shrink':fit_shrink(train)}
 raw=[_grid_probabilities(*expected_goals(f,params)) for f,_,_ in train]
 params['platt']={'|'.join(key):fit_platt([(p[key],l[key]) for p,l in zip(raw,train_labels)]) for key in train_labels[0] if key[0]!='DC'}
 return params


def _log_loss(pairs):return scores([(min(1-1e-6,max(1e-6,p)),y) for p,y in pairs])['log_loss']


def fit_direct(train,train_labels,full=None):
 """Per direct market: keep the Poisson price unless a ridge logistic beats it on the inner (later) training split."""
 inner=int(len(train)*.7);fit,check=train[:inner],train[inner:];fit_labels,check_labels=train_labels[:inner],train_labels[inner:]
 if len(check)<MIN_HOLDOUT//2:return {},{}
 base=poisson_params(fit,fit_labels)
 poisson_check=[probabilities(f,base) for f,_,_ in check]
 x_fit=[direct_features(f,base) for f,_,_ in fit];x_check=[direct_features(f,base) for f,_,_ in check]
 full=full or poisson_params(train,train_labels);x_full=[direct_features(f,full) for f,_,_ in train]
 chosen,evidence={},{}
 for market,(yes,_) in DIRECT_MARKETS.items():
  key=(market,yes);y_fit=[l[key] for l in fit_labels];y_check=[l[key] for l in check_labels]
  if not 0<sum(y_fit)<len(y_fit):continue
  poisson_loss=_log_loss([(p[key],y) for p,y in zip(poisson_check,y_check)])
  trials={}
  for r in RIDGES:
   candidate=fit_logistic(x_fit,y_fit,r)
   trials[r]=_log_loss([(logistic_probability(candidate,x),y) for x,y in zip(x_check,y_check)])
  ridge=min(trials,key=trials.get)
  evidence[market]={'inner_log_loss':{'poisson':poisson_loss,'direct':trials[ridge]},'ridge':ridge}
  if trials[ridge]<poisson_loss:chosen[market]=fit_logistic(x_full,[l[key] for l in train_labels],ridge)
 return chosen,evidence


@lru_cache(maxsize=None)
def _winning_outcomes():
 """Per scoreline on the grid, the (market, outcome) pairs it wins; plus every priced pair (computed once)."""
 cells=tuple(((i,j),tuple((mk,oc) for mk,ocs in settled_outcomes(i,j).items() for oc,st in ocs.items() if st=='WON'))
             for i in range(MAX_GOALS+1) for j in range(MAX_GOALS+1))
 return cells,tuple((mk,oc) for mk,ocs in settled_outcomes(0,0).items() for oc in ocs)


def _grid_probabilities(lh,la):
 ph=[math.exp(-lh)*lh**k/math.factorial(k) for k in range(MAX_GOALS+1)]
 pa=[math.exp(-la)*la**k/math.factorial(k) for k in range(MAX_GOALS+1)]
 norm=sum(ph)*sum(pa);cells,keys=_winning_outcomes()
 out=dict.fromkeys(keys,0.0)
 for (i,j),won in cells:
  p=ph[i]*pa[j]/norm
  for key in won:out[key]+=p
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
 params=poisson_params(train,train_labels)
 direct,selection=fit_direct(train,train_labels,params)
 if direct:params['direct']=direct
 params['direct_selection']=selection
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
                          'skill':round(1-model['brier']/base['brier'],6) if base['brier'] else None,'train_rate':round(rate,6),
                          'method':'direct_logistic' if key[0] in direct else 'poisson_grid'}
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
             'validated_at':at.isoformat(),'competition_ids':[competition_id]}
 if approved:validation.update({k:True for k in REQUIRED})
 model=m.ModelVersion(sport_id=sport_id,name=NAME,version=at.strftime('%Y%m%d.%H%M%S'),status='ACTIVE' if approved else 'CHALLENGER',validation=validation)
 db.add(model);db.flush()
 if approved:
  from app.modules.prediction.scope import competitions_for
  # Retire only market models serving the same competition; other leagues keep their own validated model.
  for old in db.scalars(select(m.ModelVersion).where(m.ModelVersion.sport_id==sport_id,m.ModelVersion.status=='ACTIVE',m.ModelVersion.id!=model.id)):
   if model_type(old)==MODEL_TYPE and competition_id in competitions_for(db,old):old.status='RETIRED'
 db.add(m.AuditEvent(actor='autonomous-model-governance',action='model.market_validation',correlation_id=model.id,
                     payload={'status':model.status,'approved_outcomes':approved,'rejected':{k:v['reasons'] for k,v in markets.items() if not v['approved']},
                              'holdout_count':n_test,'max_calibration_error':max_ece}))
 return {'model_id':model.id,'status':model.status,'approved_outcomes':len(approved),'validated_outcomes':len(markets),'holdout':n_test}


def active_model(db,sport_id,competition_id=None):
 """The validated market model for a sport; with competition_id, only one validated on that competition."""
 from app.modules.prediction.scope import in_scope
 for model in db.scalars(select(m.ModelVersion).where(m.ModelVersion.sport_id==sport_id,m.ModelVersion.status=='ACTIVE').order_by(m.ModelVersion.version.desc())):
  v=model.validation or {}
  if model_type(model)==MODEL_TYPE and all(v.get(k) is True for k in REQUIRED) and (competition_id is None or in_scope(db,model,competition_id)):return model
 return None


def infer(db,fixture,dossier_id=None,now=None):
 """Publish probabilities for every APPROVED outcome of the active market model (idempotent)."""
 from app.modules.prediction.prospective import eligible
 now=now or datetime.now(timezone.utc)
 report={'created':[],'existing':[],'blocked':[]}
 model=active_model(db,fixture.sport_id,fixture.competition_id)
 if model is None:report['blocked'].append('No market model validated on this competition');return report
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
