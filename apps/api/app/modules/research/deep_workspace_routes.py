"""Read-only Deep Match Research workspace, adapted from the supplied Figma/API patch."""
from datetime import datetime,timedelta,timezone
from fastapi import APIRouter,HTTPException
from sqlalchemy import select,func
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.research import catalog
from app.modules.research.league import verified_matches,utc
from app.modules.autonomy.service import runtime_status
from app.modules.research.service import SECTIONS as REQUIRED_SECTIONS

router=APIRouter(prefix='/api/v1/sports/research',tags=['Deep Match Research'])
SECTIONS={'head_to_head':'Head-to-Head','recent_form':'Team Form','injuries':'Injuries & Availability','lineups':'Probable Lineups',
          'match_statistics':'Match Statistics','official_result':'Official Results','team_news':'Club News & Reports','standings':'League Standings'}
ALIASES={'headtohead':'head_to_head','h2h':'head_to_head','teamform':'recent_form','recentform':'recent_form','teamrecentresults':'recent_form',
         'injuriesavailability':'injuries','injuriesandavailability':'injuries','probablelineups':'lineups',
         'matchstatistics':'match_statistics','teamnews':'team_news','clubnews':'team_news','clubnewsreports':'team_news',
         'leaguestandings':'standings','officialresults':'official_result','officialresult':'official_result','marketodds':'market_odds'}


def section_key(value):
    normalized=''.join(c for c in str(value).lower() if c.isalnum())
    return ALIASES.get(normalized,next((key for key in SECTIONS if key.replace('_','')==normalized),str(value)))


def form_freshness(payload,cutoff,observed_at):
    """Assess result dates, not the time at which an old response was captured."""
    data=payload.get('data')
    from app.modules.research.evidence_bridge import PRODUCER
    if payload.get('producer')==PRODUCER and isinstance(data,dict):
        samples=data.get('samples',{})
        if not isinstance(samples,dict) or set(samples)!={'home','away'}:return 'UNKNOWN',None
        sides=[form_freshness({'section':'team_recent_results','data':{'results':samples[side]}},cutoff,observed_at) for side in ('home','away')]
        if any(status=='UNKNOWN' for status,_ in sides):return 'UNKNOWN',None
        return ('STALE' if any(status=='STALE' for status,_ in sides) else 'RECENT'),min(stamp for _,stamp in sides)
    if payload.get('section')!='team_recent_results' or not isinstance(data,dict):
        return 'UNKNOWN',None
    results=data.get('results')
    if not isinstance(results,list) or not results:
        return 'UNKNOWN',None
    dates=[]
    for row in results:
        if not isinstance(row,dict) or not isinstance(row.get('kickoff_at'),str):
            return 'UNKNOWN',None
        try: stamp=datetime.fromisoformat(row['kickoff_at'].replace('Z','+00:00'))
        except ValueError: return 'UNKNOWN',None
        if stamp.tzinfo is None or stamp.utcoffset() is None or utc(stamp)>=min(utc(cutoff),utc(observed_at)):
            return 'UNKNOWN',None
        dates.append(utc(stamp))
    latest=max(dates)
    return ('STALE' if utc(cutoff)-latest>timedelta(days=30) else 'RECENT'),latest


def build_workspace(db,fixture_id,as_of=None):
    from app.modules.research.evidence_bridge import inspect as research_readiness
    fixture=db.get(m.Fixture,fixture_id)
    if fixture is None:raise LookupError('Fixture not found')
    cutoff=min(catalog.cutoff_time(as_of),utc(fixture.kickoff_at))
    comp=db.get(m.Competition,fixture.competition_id);sport=db.get(m.Sport,comp.sport_id)
    from app.modules.research.sport_profiles import profile,sample_metrics
    from app.modules.research.evidence_bridge import key as team_key
    readiness,samples=research_readiness(db,fixture,cutoff)
    sport_profile=profile(sport.name)
    season=db.get(m.CompetitionSeason,fixture.season_id) if fixture.season_id else None
    dossier=db.scalar(select(m.Research).where(m.Research.fixture_id==fixture.id,m.Research.created_at<=cutoff).order_by(m.Research.version.desc()).limit(1))
    observations=db.scalars(select(m.Observation).where(m.Observation.fixture_id==fixture.id,m.Observation.observed_at<cutoff).order_by(m.Observation.observed_at.desc(),m.Observation.id).limit(500)).all()
    providers={p.id:p for p in db.scalars(select(m.Source).where(m.Source.id.in_({o.source_id for o in observations}))).all()}
    refs=set(dossier.evidence_ids or []) if dossier else set()
    evidence=[]
    for o in observations:
        provider=providers.get(o.source_id);authorized=bool(provider and provider.enabled and provider.permission=='AUTHORIZED' and o.content_hash)
        payload=o.payload if isinstance(o.payload,dict) else {}
        freshness,latest_result=form_freshness(payload,cutoff,o.observed_at) if authorized else ('UNKNOWN',None)
        evidence.append(dict(id=o.id,section=section_key(payload.get('section') or payload.get('research_section') or 'fixture_provenance'),
            observed_at=o.observed_at,source_name=provider.name if provider else None,source_url=o.source_url,
            status='RECORDED_AUTHORIZED' if authorized else 'UNVERIFIED',
            verification=payload.get('verification') if authorized else None,
            source_id=o.source_id if authorized else None,dossier_linked=o.id in refs and authorized,
            freshness=freshness,latest_result_at=latest_result,
            data=payload.get('data',payload) if authorized else None))
    entries={section_key(k):v for k,v in (dossier.sections or {}).items()} if dossier else {}
    table=catalog.standings(db,comp.id,fixture.season_id,cutoff)
    section_rows=[]
    for key,label in SECTIONS.items():
        if sport.name.casefold() in ('tennis','table tennis'):
            label={'lineups':'Participants & Availability','team_news':'Player News','recent_form':'Recent Form','standings':'Rankings'}.get(key,label)
        entry=entries.get(key,{})
        entry=entry if isinstance(entry,dict) else {}
        linked=refs&set(entry.get('evidence_ids') or [])
        valid=[e for e in evidence if e['section']==key and e['id'] in linked and e['status']=='RECORDED_AUTHORIZED']
        recorded=[e for e in evidence if e['section']==key and e['status']=='RECORDED_AUTHORIZED']
        expected=set(entry.get('evidence_ids') or [])
        verified=entry.get('status')=='VERIFIED' and bool(expected) and {e['id'] for e in valid}==expected
        table_context=key=='standings' and bool(table['rows']) and table.get('mode') in ('community_computed','community_partial','source_snapshot')
        stale=bool(recorded) and all(e['freshness']=='STALE' for e in recorded)
        status=('VERIFIED' if verified else 'CONFLICTED' if entry.get('status')=='CONFLICTED' else
                'STALE' if stale else 'PROVISIONAL' if recorded or table_context else
                'UNAVAILABLE' if entry.get('status')=='UNAVAILABLE' else 'NO_VERIFIED_EVIDENCE')
        section_rows.append(dict(key=key,name=label,count=len(valid),status=status,latest_at=max((e['observed_at'] for e in valid),default=None),
                                 recorded_count=len(recorded),required=key in REQUIRED_SECTIONS,
                                 context_source=table.get('source') if table_context else None,
                                 details=entry.get('details',{})))
    count=sum(s['status']=='VERIFIED' and s['required'] for s in section_rows)
    rows=table['rows'];top=rows[:2]
    games=verified_matches(db,comp.id,cutoff,season_id=fixture.season_id) if readiness['research_adapter'] else []
    meetings=[g for g in games if {g['home_id'],g['away_id']}=={fixture.home_name,fixture.away_name}][:5]
    sampled_meetings={}
    for source_id,sides in samples.items():
        for _,sample in sides.values():
            for result in sample:
                if {result['home'],result['away']}!={team_key(fixture.home_name),team_key(fixture.away_name)}:continue
                identity=(result['kickoff_at'],result['home'],result['away'],result['home_score'],result['away_score'])
                sampled_meetings.setdefault(identity,dict(id='sample-'+str(len(sampled_meetings)),kickoff_at=result['kickoff_at'],
                    home=fixture.home_name if result['home']==team_key(fixture.home_name) else fixture.away_name,
                    away=fixture.away_name if result['away']==team_key(fixture.away_name) else fixture.home_name,
                    home_score=result['home_score'],away_score=result['away_score'],basis='PROVISIONAL_SAMPLE',source_id=source_id))
    def team(name,side):
        row=next((r for r in rows if r['club']==name),None)
        played=[g for g in games if name in (g['home_id'],g['away_id'])]
        scores=[(g['home_score'],g['away_score']) if g['home_id']==name else (g['away_score'],g['home_score']) for g in played]
        source_id=None;parent=None;sample=[]
        if not scores:
            options=[(sid,*sides[side]) for sid,sides in samples.items() if side in sides]
            if options:
                source_id,parent,sample=max(options,key=lambda item:(item[2][0]['kickoff_at'],len(item[2]),utc(item[1].observed_at)))
                scores=[(r['home_score'],r['away_score']) if r['home']==team_key(name) else (r['away_score'],r['home_score']) for r in sample]
        metrics=sample_metrics(scores,sport.name)
        metrics['form']=metrics['form'] or (row.get('form') if row else None) or []
        source=db.get(m.Source,source_id) if source_id else None
        return dict(name=name,standing=row,**metrics,
                    average_goals=metrics['average_score'] if sport_profile['score_unit']=='goals' else None,
                    basis='PROVISIONAL_SAMPLE' if source_id else 'VERIFIED_RESULTS' if scores else 'NO_DATA',
                    source_id=source_id,source_name=source.name if source else None,
                    evidence_ids=next((report['sides'][side]['evidence_ids'] for report in readiness['providers'] if report['source_id']==source_id and side in report['sides']),[]),results=sample,
                    latest_result_at=sample[0]['kickoff_at'] if sample else played[0]['kickoff'] if played else None,
                    coverage='PARTIAL' if source_id else 'VERIFIED_RESULTS' if scores else 'MISSING')
    runtime=runtime_status(db)
    run=db.scalar(select(m.PipelineRun).where(m.PipelineRun.fixture_id==fixture.id).order_by(m.PipelineRun.updated_at.desc()).limit(1))
    stage_rows=db.scalars(select(m.PipelineStage).where(m.PipelineStage.run_id==run.id)).all() if run else []
    stages={s.stage_key:s.status for s in stage_rows}
    stage_errors={s.stage_key:dict(code=s.failure_code,reason=s.error) for s in stage_rows if s.error}
    authorized_sources={o.source_id for o in observations if (p:=providers.get(o.source_id)) and p.enabled and p.permission=='AUTHORIZED'}
    return dict(fixture=dict(id=fixture.id,home=fixture.home_name,away=fixture.away_name,kickoff_at=fixture.kickoff_at,status=fixture.status,matchday=fixture.matchday,
                             competition_id=comp.id,competition=comp.name,sport=sport.name,country=comp.country,season_id=fixture.season_id,season=season.label if season else None),
        cutoff=cutoff,dossier_id=dossier.id if dossier else None,version=dossier.version if dossier else None,
        status='VERIFIED' if count==len(REQUIRED_SECTIONS) else 'INCOMPLETE',last_research_at=dossier.created_at if dossier else None,
        sections=section_rows,evidence=evidence,verified_sections=count,total_sections=len(REQUIRED_SECTIONS),sample_limit=500,
        research_readiness=readiness,sport_profile=sport_profile,
        summary=dict(home=team(fixture.home_name,'home'),away=team(fixture.away_name,'away'),top_two=top,table_mode=table['mode'],table_warning=table.get('warning'),table_source=table.get('source'),
                     head_to_head=[dict(id=g['id'],kickoff_at=g['kickoff'],home=g['home_id'],away=g['away_id'],home_score=g['home_score'],away_score=g['away_score'],basis='VERIFIED_RESULTS') for g in meetings] or sorted(sampled_meetings.values(),key=lambda row:row['kickoff_at'],reverse=True)[:5]),
        metrics=dict(research_runs=db.scalar(select(func.count()).select_from(m.Research)) or 0,
                     fixtures_researched=db.scalar(select(func.count(func.distinct(m.Research.fixture_id)))) or 0,
                     evidence_items=db.scalar(select(func.count()).select_from(m.Observation).join(m.Source).where(m.Source.enabled.is_(True),m.Source.permission=='AUTHORIZED')) or 0),
        sources=dict(authorized=len(authorized_sources),recorded=len(providers),online=None),
        runtime=dict(status=runtime['status'],worker_online=runtime['worker_online'],next_run_at=runtime.get('next_run_at'),stages=stages,stage_errors=stage_errors),
        message='Verified coverage requires section-specific links to authorized pre-match evidence. Provisional observations and league context do not establish verification. Form is marked stale when its latest recorded result is over 30 days old; recent dates do not establish complete coverage.')


@router.get('/workspace/{fixture_id}')
def workspace(fixture_id:str,as_of:datetime|None=None):
    try:
        with SessionLocal() as db:return build_workspace(db,fixture_id,as_of)
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
