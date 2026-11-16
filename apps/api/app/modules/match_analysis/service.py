"""Evidence-first Match Analysis workspace (v3.6 patch, adapted to the canonical research workspace).

Nothing here is simulated: statistics come from verified results before the cutoff, comparison metrics
come from feature snapshots linked to VERIFIED dossiers and authorized evidence, and probabilities come
only from persisted forecasts of ACTIVE models made before the cutoff.
"""
from datetime import datetime,timezone
from sqlalchemy import select,func
from app.db import models as m
from app.modules.research.deep_workspace_routes import build_workspace
from app.modules.research.league import utc

FORM_METRICS=[('goals_per_match','Goals per Match'),('goals_conceded','Goals Conceded'),('xg_per_match','xG (Expected Goals)'),
              ('xga_per_match','xGA (Expected Against)'),('clean_sheet_rate','Clean Sheet Rate')]
FEATURE_METRICS=[('attack_strength','Attack Strength'),('defence_strength','Defence Strength'),('midfield_control','Midfield Control'),
                 ('form_rating','Form Rating'),('home_advantage','Home Advantage')]
TACTICAL={'attack_strength','defence_strength','midfield_control'}
METRIC_ALIASES={'goals_for_per_match':'goals_per_match','goals_against_per_match':'goals_conceded'}
EVIDENCE_GROUPS=[('match_statistics','Match Statistics',{'match_statistics'}),('team_news','Team News & Injuries',{'team_news','injuries'}),
                 ('lineups','Lineups (Probable)',{'lineups'}),('historical','Historical Results',{'head_to_head','official_result','recent_form','standings'})]


def iso(value):return value.isoformat() if value else None


def number(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)):return None
    return float(value) if -100000<float(value)<100000 else None


def feature_metrics(raw):
    """Accept home/away metric pairs at the snapshot top level or under 'metrics'."""
    out={}
    if not isinstance(raw,dict):return out
    nested=raw.get('metrics') if isinstance(raw.get('metrics'),dict) else {}
    for container in (raw,nested):
        for key,value in container.items():
            key=METRIC_ALIASES.get(key,key)
            if isinstance(value,dict) and number(value.get('home')) is not None and number(value.get('away')) is not None:
                out[key]=dict(home=number(value['home']),away=number(value['away']),unit=str(value.get('unit') or ''),
                              evidence_ids=[str(i) for i in value.get('evidence_ids') or []])
    return out


def authorized_evidence(db,fixture_id,ids,cutoff):
    if not ids:return {}
    rows=db.execute(select(m.Observation,m.Source).join(m.Source,m.Observation.source_id==m.Source.id)
                    .where(m.Observation.id.in_(list(ids)),m.Observation.fixture_id==fixture_id,m.Observation.observed_at<=cutoff,
                           m.Source.enabled.is_(True),m.Source.permission=='AUTHORIZED')).all()
    return {o.id:o for o,_ in rows}


def latest_feature(db,fixture_id,cutoff):
    """Newest snapshot at/before cutoff whose dossier is VERIFIED and backed by authorized evidence."""
    versions=db.execute(select(m.Feature,m.Research).join(m.Research,m.Feature.research_id==m.Research.id)
                        .where(m.Research.fixture_id==fixture_id,m.Feature.cutoff_at<=cutoff).order_by(m.Feature.cutoff_at.desc()).limit(25)).all()
    for feature,research in versions:
        raw=feature.features if isinstance(feature.features,dict) else {}
        ids=set(raw.get('evidence_ids') or [])|set(research.evidence_ids or [])
        evidence=authorized_evidence(db,fixture_id,ids,cutoff)
        if research.status=='VERIFIED' and evidence:
            metrics={k:v for k,v in feature_metrics(raw).items() if set(v['evidence_ids'])<=set(evidence)}
            return feature,research,evidence,metrics,len(versions)
    return None,None,{},{},len(versions)


def probabilities(db,fixture_id,cutoff):
    rows=db.execute(select(m.Prediction,m.ModelVersion).join(m.ModelVersion,m.Prediction.model_id==m.ModelVersion.id)
                    .where(m.Prediction.fixture_id==fixture_id,m.Prediction.market_key=='1X2',m.Prediction.predicted_at<=cutoff,
                           m.ModelVersion.status=='ACTIVE').order_by(m.Prediction.predicted_at.desc())).all()
    out=dict(home=None,draw=None,away=None,model=None,predicted_at=None)
    for prediction,model in rows:
        key=str(prediction.outcome_key).lower()
        if key in ('home','draw','away') and out[key] is None:
            out[key]=round(float(prediction.probability)*100,1)
            if out['predicted_at'] is None:out.update(model=model.name+' '+model.version,predicted_at=prediction.predicted_at)
    return out


def workspace(db,fixture_id,as_of=None):
    ws=build_workspace(db,fixture_id,as_of)
    cutoff=utc(ws['cutoff']);home,away=ws['summary']['home'],ws['summary']['away']
    feature,research,feature_evidence,metrics,versions=latest_feature(db,fixture_id,cutoff)
    computed=dict(goals_per_match=(home['average_goals'],away['average_goals'],''),goals_conceded=(home['average_conceded'],away['average_conceded'],''),
                  clean_sheet_rate=(home['clean_sheet_pct'],away['clean_sheet_pct'],'%'))
    form_rows=[]
    for key,label in FORM_METRICS:
        if key in metrics:form_rows.append(dict(key=key,label=label,home=metrics[key]['home'],away=metrics[key]['away'],unit=metrics[key]['unit'],basis='FEATURE_SNAPSHOT'))
        elif key in computed and None not in computed[key][:2]:
            form_rows.append(dict(key=key,label=label,home=computed[key][0],away=computed[key][1],unit=computed[key][2],basis='VERIFIED_RESULTS'))
    comparison=[dict(key=k,label=label,**{f:metrics[k][f] for f in ('home','away','unit')}) for k,label in FEATURE_METRICS if k in metrics]
    sections={s['key']:s['status'] for s in ws['sections']}
    sampled=home['sample_size']>0 and away['sample_size']>0
    def state(key,fallback):return 'VERIFIED' if sections.get(key)=='VERIFIED' else 'COMPUTED' if fallback else 'MISSING'
    rows=[dict(key='statistics',name='Statistical Analysis',status=state('match_statistics',sampled)),
             dict(key='form',name='Team Form Analysis',status=state('recent_form',sampled)),
             dict(key='head_to_head',name='Head-to-Head Analysis',status=state('head_to_head',bool(ws['summary']['head_to_head']))),
             dict(key='availability',name='Injuries & Lineup Status',status='VERIFIED' if sections.get('injuries')==sections.get('lineups')=='VERIFIED' else 'MISSING'),
             dict(key='tactics',name='Tactical Matchup',status='VERIFIED' if TACTICAL&set(metrics) else 'MISSING'),
             dict(key='features',name='Feature Engineering',status='VERIFIED' if feature and metrics else 'MISSING')]
    verified=sum(r['status']=='VERIFIED' for r in rows)
    authorized=[e for e in ws['evidence'] if e['status']=='RECORDED_AUTHORIZED']
    tactical_ids={i for k in TACTICAL&set(metrics) for i in metrics[k]['evidence_ids']}
    groups=[dict(key=k,name=name,count=sum(e['section'] in keys for e in authorized)) for k,name,keys in EVIDENCE_GROUPS]
    groups+=[dict(key='tactics',name='Tactical Analysis',count=len(tactical_ids)),dict(key='sources',name='External Sources',count=ws['sources']['authorized'])]
    xg=metrics.get('xg_per_match')
    return dict(fixture=ws['fixture'],cutoff=ws['cutoff'],status='VERIFIED' if verified==len(rows) else 'PARTIAL' if verified else 'INSUFFICIENT_DATA',
        teams=dict(home=home,away=away),probabilities=probabilities(db,fixture_id,cutoff),
        expected_goals=dict(home=xg['home'],away=xg['away']) if xg else None,form_metrics=form_rows,feature_comparison=comparison,
        head_to_head=ws['summary']['head_to_head'],summary=rows,verified_rows=verified,evidence_groups=groups,
        evidence=ws['evidence'],sections=ws['sections'],
        metadata=dict(analysis_id=feature.id if feature else None,research_id=research.id if research else None,research_version=research.version if research else None,
                      feature_versions=versions,last_analysis_at=feature.cutoff_at if feature else None,
                      data_freshness_at=max((e['observed_at'] for e in authorized),default=None),next_update_at=ws['runtime']['next_run_at']),
        metrics=dict(summary(db),evidence_items=ws['metrics']['evidence_items'],coverage=round(verified*100/len(rows),1)),
        runtime=ws['runtime'],
        message='Statistics marked "computed" come from verified results before the cutoff. Comparison metrics require a VERIFIED dossier, '
                'authorized evidence and a feature snapshot; probabilities require an ACTIVE model. Missing values are not simulated.')


def summary(db):
    return dict(analysis_records=db.scalar(select(func.count()).select_from(m.Feature)) or 0,
                analysed_matches=db.scalar(select(func.count(func.distinct(m.Research.fixture_id))).select_from(m.Feature)
                                           .join(m.Research,m.Feature.research_id==m.Research.id)) or 0,
                research_dossiers=db.scalar(select(func.count()).select_from(m.Research)) or 0,
                updated_at=datetime.now(timezone.utc).isoformat())
