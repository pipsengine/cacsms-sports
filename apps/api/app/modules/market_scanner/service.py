"""Market catalogue and paper-only prediction evaluation (adapted from the cacsms-market-scanner patch).

The patch's standalone ms_* tables are NOT used: markets are discovered from canonical markets.odds_snapshots,
forecasts come from predictions.forecasts of ACTIVE models, and every evaluation runs the existing
markets.service.evaluate_market gates. Nothing is persisted here; no bookmaker account automation or scraping.
"""
import re
from collections import defaultdict
from types import SimpleNamespace
from datetime import datetime,timezone,timedelta
from sqlalchemy import select,func
from app.db import models as m
from app.modules.markets.service import evaluate_market
from app.modules.match_analysis.service import workspace as analysis_workspace
from app.modules.research.league import utc

FAMILIES=['Main Markets','Goals Markets','Both Teams to Score','Double Chance','Handicap Markets','Totals / Over-Under','Half Time Markets','Correct Score','Multigoals','Other Markets']
NAMES={'1X2':'1X2 (Match Result)','MATCHRESULT':'1X2 (Match Result)','BTTS':'Both Teams to Score','GG/NG':'Both Teams to Score','DC':'Double Chance',
       'DOUBLECHANCE':'Double Chance','DNB':'Draw No Bet','CS':'Correct Score','CORRECTSCORE':'Correct Score','HT1X2':'Half Time 1X2','HTFT':'Half Time / Full Time'}
OUTCOMES={'HOME':'Home','DRAW':'Draw','AWAY':'Away','YES':'Yes','NO':'No','OVER':'Over','UNDER':'Under','1X':'1X','X2':'X2','12':'12'}
FRESH=timedelta(minutes=15)


def aware(row,*fields):
    """Read-only copy with timezone-aware timestamps (SQLite returns naive values); ORM rows are never mutated."""
    values={c:getattr(row,c) for c in row.__table__.columns.keys()}
    values.update({f:utc(values[f]) for f in fields})
    return SimpleNamespace(**values)


def compact(key):return re.sub(r'[^A-Z0-9/.]','',str(key).upper())


def family(key):
    k=compact(key)
    if k.startswith(('HT','1H','2H','HALF')) or 'HALFTIME' in k:return 'Half Time Markets'
    if k in ('1X2','MATCHRESULT','DNB','DRAWNOBET','FT1X2'):return 'Main Markets'
    if k.startswith(('BTTS','GG')):return 'Both Teams to Score'
    if k.startswith(('DC','DOUBLECHANCE')):return 'Double Chance'
    if k.startswith(('AH','EH','HANDICAP','ASIAN')):return 'Handicap Markets'
    if k.startswith(('CS','CORRECTSCORE')):return 'Correct Score'
    if k.startswith('MULTIGOAL'):return 'Multigoals'
    if k.startswith(('OU','OVERUNDER','TOTAL')):return 'Totals / Over-Under'
    if 'GOAL' in k:return 'Goals Markets'
    return 'Other Markets'


def market_name(key):
    k=compact(key)
    if k in NAMES:return NAMES[k]
    line=re.search(r'(\d+(?:[._]\d+)?)$',str(key))
    value=line.group(1).replace('_','.') if line else ''
    if k.startswith('HOMEOU'):return ('Home Over/Under '+value).strip()
    if k.startswith('AWAYOU'):return ('Away Over/Under '+value).strip()
    if k=='ODDEVEN':return 'Odd/Even Goals'
    if k.startswith(('OU','OVERUNDER','TOTAL')):return ('Over/Under '+value).strip()
    if k.startswith('AH') or k.startswith('ASIAN'):return ('Asian Handicap '+value).strip()
    return str(key).replace('_',' ').title()


def outcome_name(key):return OUTCOMES.get(str(key).upper(),str(key).replace('_',' ').title())


def selection_name(market_key,outcome_key):
    """Selection label as bookmakers show it: totals carry their line ('Over 2.5'), 1X2 carries its code ('Home (1)')."""
    line=re.search(r'_(-?\d+(?:\.\d+)?)$',str(market_key))
    name=outcome_name(outcome_key)
    if line and str(outcome_key).upper() in ('OVER','UNDER'):return f'{name} {line.group(1)}'
    if compact(market_key)=='1X2':return {'HOME':'Home (1)','DRAW':'Draw (X)','AWAY':'Away (2)'}.get(str(outcome_key).upper(),name)
    return name


MARKET_ORDER=('1X2','DC','OU','HOME_OU','AWAY_OU','BTTS','ODD_EVEN','AH','CS')
OUTCOME_ORDER={k:i for i,k in enumerate(('HOME','DRAW','AWAY','1X','X2','12','OVER','UNDER','YES','NO','ODD','EVEN'))}


def market_sort_key(market_key,outcome_key):
    base=re.sub(r'_-?\d+(?:\.\d+)?$','',str(market_key))
    line=re.search(r'_(-?\d+(?:\.\d+)?)$',str(market_key))
    return (MARKET_ORDER.index(base) if base in MARKET_ORDER else 99,float(line.group(1)) if line else 0,OUTCOME_ORDER.get(str(outcome_key).upper(),50),str(outcome_key))


def latest_quotes(db,fixture_id,cutoff):
    rows=db.scalars(select(m.Odds).where(m.Odds.fixture_id==fixture_id,m.Odds.observed_at<=cutoff).order_by(m.Odds.observed_at.desc(),m.Odds.id)).all()
    out={}
    for row in rows:out.setdefault((row.bookmaker,row.market_key,row.outcome_key),row)
    return out


def pick_bookmaker(names,requested=None):
    names=sorted(names)
    if requested and requested in names:return requested
    return next((n for n in names if n.casefold()=='sportybet'),names[0] if names else None)


def build_markets(quotes,bookmaker):
    grouped={}
    for (book,market,outcome),row in quotes.items():
        if book!=bookmaker:continue
        entry=grouped.setdefault(market,dict(key=market,name=market_name(market),family=family(market),selections=[],observed_at=None))
        entry['selections'].append(dict(key=outcome,name=outcome_name(outcome),odds=float(row.decimal_odds),odds_id=row.id,observed_at=row.observed_at))
        entry['observed_at']=max(filter(None,[entry['observed_at'],row.observed_at]))
    order={k:i for i,k in enumerate(['HOME','DRAW','AWAY','1X','X2','12','YES','NO','OVER','UNDER'])}
    for entry in grouped.values():entry['selections'].sort(key=lambda s:(order.get(str(s['key']).upper(),99),str(s['key'])))
    return sorted(grouped.values(),key=lambda e:(FAMILIES.index(e['family']),e['name']))


def interval(details):
    data=(details or {}).get('interval') if isinstance(details,dict) else None
    if not isinstance(data,dict):return None,None
    lower,upper=data.get('lower'),data.get('upper')
    ok=lambda v:isinstance(v,(int,float)) and not isinstance(v,bool) and 0<=v<=1
    return (float(lower) if ok(lower) else None,float(upper) if ok(upper) else None)


def forecasts(db,fixture_id,cutoff):
    rows=db.execute(select(m.Prediction,m.ModelVersion).join(m.ModelVersion,m.Prediction.model_id==m.ModelVersion.id)
                    .where(m.Prediction.fixture_id==fixture_id,m.Prediction.predicted_at<=cutoff,m.ModelVersion.status=='ACTIVE')
                    .order_by(m.Prediction.predicted_at.desc(),m.Prediction.id)).all()
    # One model per market so its outcomes stay coherent: most outcomes covered, then best holdout Brier, then newest.
    latest={}
    for prediction,model in rows:latest.setdefault((prediction.market_key,model.id,prediction.outcome_key),(prediction,model))
    per=defaultdict(lambda:defaultdict(dict))
    for (market,model_id,outcome),pair in latest.items():per[market][model_id][outcome]=pair
    def brier(pair):
        prediction,model=pair;d=prediction.details if isinstance(prediction.details,dict) else {};v=model.validation if isinstance(model.validation,dict) else {}
        value=d.get('holdout_brier',(v.get('holdout_metrics') or {}).get('brier'))
        return float(value) if isinstance(value,(int,float)) else 1.0
    out={}
    for market,models in per.items():
        best=min(models.values(),key=lambda pairs:(-len(pairs),sum(brier(p) for p in pairs.values())/len(pairs)))
        for outcome,pair in best.items():out[(market,outcome)]=pair
    return out


def evaluate(db,prediction,model,quote,now):
    lower,upper=interval(prediction.details)
    probability=float(prediction.probability)
    skill=(prediction.details or {}).get('skill') if isinstance(prediction.details,dict) else None
    row=dict(skill=round(skill*100,1) if isinstance(skill,(int,float)) else None,prediction_id=prediction.id,market_key=prediction.market_key,market=market_name(prediction.market_key),family=family(prediction.market_key),
             outcome_key=prediction.outcome_key,selection=outcome_name(prediction.outcome_key),probability=round(probability*100,1),
             lower=round(lower*100,1) if lower is not None else None,upper=round(upper*100,1) if upper is not None else None,
             model=model.name+' '+model.version,predicted_at=prediction.predicted_at,odds=None,odds_observed_at=None,ev=None,conservative_ev=None,
             decision='NO_MARKET_PRICE',reasons=['NO_MATCHING_BOOKMAKER_PRICE'],gates={})
    if quote is None:return row
    odds=float(quote.decimal_odds)
    row.update(odds=odds,odds_observed_at=quote.observed_at,ev=round((probability*odds-1)*100,1),
               conservative_ev=round((lower*odds-1)*100,1) if lower is not None else None)
    feature=db.get(m.Feature,prediction.feature_id);research=db.get(m.Research,feature.research_id) if feature else None
    if feature is None or research is None:
        row.update(decision='REJECTED',reasons=['MISSING_FEATURE_OR_RESEARCH']);return row
    verdict=evaluate_market(aware(prediction,'predicted_at'),aware(quote,'observed_at'),model,aware(feature,'cutoff_at'),aware(research,'created_at'),now=now)
    reasons=list(verdict['reason_codes'])
    if row['conservative_ev'] is None:reasons.append('NO_PROBABILITY_INTERVAL')
    elif row['conservative_ev']<=0:reasons.append('NO_CONSERVATIVE_EDGE')
    row.update(decision='QUALIFIED' if verdict['decision']=='QUALIFIED' and not reasons else 'REJECTED',reasons=reasons,gates=verdict['gates'])
    return row


def rank_key(row):
    # Priced: qualification, lower bound, lower-bound EV. Unpriced: validated skill over the base rate ("most suitable for analysis").
    unpriced=row['odds'] is None
    lower=row['lower'] if row['lower'] is not None else -1
    skill=row.get('market_skill',row.get('skill'))
    return (row['decision']!='QUALIFIED',unpriced,-(skill if skill is not None else -100) if unpriced else -lower,
            -row['probability'] if unpriced else -(row['conservative_ev'] if row['conservative_ev'] is not None else -1000),-row['probability'])


def confidence(probabilities):
    widths=[u-l for l,u in probabilities if l is not None and u is not None]
    if not widths:return None
    width=max(widths)
    return 'High' if width<=10 else 'Medium' if width<=20 else 'Low'


def ordinal(v):return str(v)+('th' if 10<=v%100<=20 else {1:'st',2:'nd',3:'rd'}.get(v%10,'th'))


def record(form):
    values=form if isinstance(form,list) else re.findall('[WDL]',form or '')
    values=values[-5:]
    return '%dW, %dD, %dL'%(values.count('W'),values.count('D'),values.count('L')) if values else None


def insights(analysis,outcomes):
    f=analysis['fixture'];home,away=analysis['teams']['home'],analysis['teams']['away'];items=[]
    if home['standing'] and away['standing']:
        hr=home['standing'].get('rank') or home['standing'].get('computed_rank');ar=away['standing'].get('rank') or away['standing'].get('computed_rank')
        if hr and ar:items.append('%s %s (%s pts); %s %s (%s pts).'%(f['home'],ordinal(hr),home['standing']['points'],f['away'],ordinal(ar),away['standing']['points']))
    for team in (home,away):
        text=record(team['form'])
        if text:items.append('%s last 5: %s.'%(team['name'],text))
    if analysis['expected_goals']:items.append('Expected goals: %s vs %s.'%(analysis['expected_goals']['home'],analysis['expected_goals']['away']))
    verdict=None
    if {'HOME','DRAW','AWAY'}<=set(outcomes):
        key,value=max(outcomes.items(),key=lambda kv:kv[1])
        verdict='Model favours %s (%.1f%%).'%({'HOME':'home win','DRAW':'draw','AWAY':'away win'}[key],value)
    elif 'HOME' in outcomes:
        # A home-win-only model cannot name a favourite among three outcomes.
        verdict='Home win probability %.1f%%; not a home win %.1f%% (draw/away not modelled separately).'%(outcomes['HOME'],100-outcomes['HOME'])
    return items,verdict


def kpis(db,sport_id):
    from app.modules.prediction.market_model import model_type
    active=next((x for x in db.scalars(select(m.ModelVersion).where(m.ModelVersion.sport_id==sport_id,m.ModelVersion.status=='ACTIVE')) if model_type(x)=='logistic'),None)
    holdout=(active.validation or {}).get('holdout_metrics') if active and isinstance(active.validation,dict) else None
    avg=db.scalar(select(func.avg(m.Prediction.probability)))
    return dict(fixtures_analysed=db.scalar(select(func.count(func.distinct(m.Prediction.fixture_id)))) or 0,
                predictions=db.scalar(select(func.count()).select_from(m.Prediction)) or 0,
                model_brier=holdout.get('brier') if isinstance(holdout,dict) else None,
                average_probability=round(float(avg)*100,1) if avg is not None else None)


def models(db,sport_id):
    rows=db.scalars(select(m.ModelVersion).where(m.ModelVersion.sport_id==sport_id).order_by(m.ModelVersion.status!='ACTIVE',m.ModelVersion.name,m.ModelVersion.version)).all()
    out=[]
    for model in rows[:20]:
        v=model.validation if isinstance(model.validation,dict) else {}
        hold=v.get('holdout_metrics') if isinstance(v.get('holdout_metrics'),dict) else {}
        base=v.get('baseline_metrics') if isinstance(v.get('baseline_metrics'),dict) else {}
        out.append(dict(id=model.id,name=model.name,version=model.version,status=model.status,approved=v.get('approved') is True,
                        calibration_verified=v.get('calibration_verified') is True,calibration_error=v.get('calibration_error'),
                        holdout_brier=hold.get('brier'),baseline_brier=base.get('brier'),holdout_count=v.get('holdout_count')))
    return out


def workspace(db,fixture_id,as_of=None,bookmaker=None,now=None):
    analysis=analysis_workspace(db,fixture_id,as_of)
    cutoff=utc(analysis['cutoff']);now=min(now or datetime.now(timezone.utc),cutoff) if as_of else (now or datetime.now(timezone.utc))
    fixture=db.get(m.Fixture,fixture_id);sport_id=db.get(m.Competition,fixture.competition_id).sport_id
    quotes=latest_quotes(db,fixture_id,cutoff)
    books={b for b,_,_ in quotes};selected=pick_bookmaker(books,bookmaker)
    markets=build_markets(quotes,selected)
    predicted=forecasts(db,fixture_id,cutoff)
    rows=[evaluate(db,p,model,quotes.get((selected,p.market_key,p.outcome_key)),now) for p,model in predicted.values()]
    # Unpriced suitability is a market-level property: every outcome inherits its market's best validated skill.
    market_skill={}
    for r in rows:market_skill[r['market_key']]=max(market_skill.get(r['market_key'],-100),r['skill'] if r['skill'] is not None else -100)
    for r in rows:r['market_skill']=r['skill'] if r['market_key']=='CS' else market_skill[r['market_key']]  # exact scores are separate events
    rows.sort(key=rank_key)
    for market in markets:
        for sel in market['selections']:sel['predicted']=(market['key'],sel['key']) in predicted
    pairs=sum(len(mk['selections']) for mk in markets);modelled=sum(s['predicted'] for mk in markets for s in mk['selections'])
    one=[r for r in rows if compact(r['market_key']) in ('1X2','MATCHRESULT')]
    outcomes={str(r['outcome_key']).upper():r['probability'] for r in one if str(r['outcome_key']).upper() in ('HOME','DRAW','AWAY')}
    statements,verdict=insights(analysis,outcomes)
    last_sync=db.scalar(select(func.max(m.Odds.observed_at)).where(m.Odds.bookmaker==selected)) if selected else None
    stages=analysis['runtime']['stages']
    fresh=any(s['observed_at'] and now-utc(s['observed_at'])<=FRESH for mk in markets for s in mk['selections'])
    pipeline=[('markets','Markets','VERIFIED' if fresh else 'STALE' if markets else None),('collect','Collect',stages.get('acquire')),('research','Research',stages.get('research')),
              ('features','Features',stages.get('analyse')),('model','Model','VERIFIED' if predicted else None),('predict','Predict',stages.get('predict') or ('VERIFIED' if predicted else None)),
              ('validate','Validate',stages.get('evaluate'))]
    history=db.execute(select(m.Prediction,m.ModelVersion).join(m.ModelVersion,m.Prediction.model_id==m.ModelVersion.id)
                       .where(m.Prediction.fixture_id==fixture_id).order_by(m.Prediction.predicted_at.desc()).limit(100)).all()
    return dict(fixture=analysis['fixture'],cutoff=analysis['cutoff'],teams=analysis['teams'],
        bookmakers=sorted(books),bookmaker=selected,markets=markets,families=[dict(name=n,count=sum(mk['family']==n for mk in markets)) for n in FAMILIES],
        coverage=dict(selections=pairs,modelled=modelled,percent=round(modelled*100/pairs,1) if pairs else None,inventory='UNVERIFIED',
                      last_sync=last_sync,next_sync=analysis['runtime']['next_run_at'],fresh=fresh),
        outcome=dict(probabilities=outcomes,confidence=confidence([(r['lower'],r['upper']) for r in one])),
        evaluations=rows,insights=statements,verdict=verdict,key_metrics=[r for r in analysis['form_metrics'] if r['key']=='xg_per_match']+[r for r in analysis['feature_comparison'] if r['key'] in ('attack_strength','defence_strength')],
        expected_goals=analysis['expected_goals'],research=dict(summary=analysis['summary'],evidence_groups=analysis['evidence_groups'],evidence=analysis['evidence']),
        models=models(db,sport_id),pipeline=[dict(key=k,name=n,status=s) for k,n,s in pipeline],
        history=[dict(id=p.id,market=market_name(p.market_key),selection=outcome_name(p.outcome_key),probability=round(float(p.probability)*100,1),
                      model=mv.name+' '+mv.version,model_status=mv.status,predicted_at=p.predicted_at,after_cutoff=utc(p.predicted_at)>cutoff) for p,mv in history],
        metrics=kpis(db,sport_id),runtime=analysis['runtime'],
        message='Markets are those observed in stored, source-backed odds snapshots; completeness of any bookmaker catalogue is not verified. '
                'Probabilities come only from ACTIVE models before the cutoff. "Qualified" requires every evaluate_market gate plus a positive '
                'lower-bound expected value and is a paper-review flag, not betting advice.')


def catalog(db,bookmaker=None):
    books=sorted(db.scalars(select(m.Odds.bookmaker).distinct()).all());selected=pick_bookmaker(books,bookmaker)
    keys=db.scalars(select(m.Odds.market_key).where(m.Odds.bookmaker==selected).distinct()).all() if selected else []
    markets=sorted((dict(key=k,name=market_name(k),family=family(k)) for k in keys),key=lambda e:(FAMILIES.index(e['family']),e['name']))
    return dict(bookmakers=books,bookmaker=selected,markets=markets,discovered_count=len(markets),
                completeness='UNVERIFIED — no authoritative bookmaker inventory is available',
                last_sync=db.scalar(select(func.max(m.Odds.observed_at)).where(m.Odds.bookmaker==selected)) if selected else None)
