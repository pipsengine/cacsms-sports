"""Read-only Deep Match Research workspace, adapted from the supplied Figma/API patch."""
from datetime import datetime,timezone
from fastapi import APIRouter,HTTPException
from sqlalchemy import select,func
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.research import catalog
from app.modules.research.league import verified_matches,utc
from app.modules.autonomy.service import runtime_status

router=APIRouter(prefix='/api/v1/sports/research',tags=['Deep Match Research'])
SECTIONS={'head_to_head':'Head-to-Head','recent_form':'Team Form','injuries':'Injuries & Availability','lineups':'Probable Lineups',
          'match_statistics':'Match Statistics','official_result':'Official Results','team_news':'Club News & Reports','standings':'League Standings'}
ALIASES={'headtohead':'head_to_head','h2h':'head_to_head','teamform':'recent_form','recentform':'recent_form',
         'injuriesavailability':'injuries','injuriesandavailability':'injuries','probablelineups':'lineups',
         'matchstatistics':'match_statistics','teamnews':'team_news','clubnews':'team_news','clubnewsreports':'team_news',
         'leaguestandings':'standings','officialresults':'official_result','officialresult':'official_result','marketodds':'market_odds'}


def section_key(value):
    normalized=''.join(c for c in str(value).lower() if c.isalnum())
    return ALIASES.get(normalized,next((key for key in SECTIONS if key.replace('_','')==normalized),str(value)))


def build_workspace(db,fixture_id,as_of=None):
    fixture=db.get(m.Fixture,fixture_id)
    if fixture is None:raise LookupError('Fixture not found')
    cutoff=min(catalog.cutoff_time(as_of),utc(fixture.kickoff_at))
    comp=db.get(m.Competition,fixture.competition_id);sport=db.get(m.Sport,comp.sport_id)
    season=db.get(m.CompetitionSeason,fixture.season_id) if fixture.season_id else None
    dossier=db.scalar(select(m.Research).where(m.Research.fixture_id==fixture.id,m.Research.created_at<=cutoff).order_by(m.Research.version.desc()).limit(1))
    observations=db.scalars(select(m.Observation).where(m.Observation.fixture_id==fixture.id,m.Observation.observed_at<cutoff).order_by(m.Observation.observed_at.desc(),m.Observation.id).limit(500)).all()
    providers={p.id:p for p in db.scalars(select(m.Source).where(m.Source.id.in_({o.source_id for o in observations}))).all()}
    evidence=[]
    for o in observations:
        provider=providers.get(o.source_id);authorized=bool(provider and provider.enabled and provider.permission=='AUTHORIZED')
        payload=o.payload if isinstance(o.payload,dict) else {}
        evidence.append(dict(id=o.id,section=section_key(payload.get('section') or payload.get('research_section') or 'fixture_provenance'),
            observed_at=o.observed_at,source_name=provider.name if provider else None,source_url=o.source_url,
            status='RECORDED_AUTHORIZED' if authorized else 'UNVERIFIED',data=payload.get('data',payload) if authorized else None))
    refs=set(dossier.evidence_ids or []) if dossier else set()
    entries={section_key(k):v for k,v in (dossier.sections or {}).items()} if dossier else {}
    section_rows=[]
    for key,label in SECTIONS.items():
        entry=entries.get(key,{})
        entry=entry if isinstance(entry,dict) else {}
        linked=refs&set(entry.get('evidence_ids') or [])
        valid=[e for e in evidence if e['section']==key and e['id'] in linked and e['status']=='RECORDED_AUTHORIZED']
        verified=entry.get('status')=='VERIFIED' and bool(valid)
        status='VERIFIED' if verified else 'UNAVAILABLE' if entry.get('status')=='UNAVAILABLE' else 'NO_VERIFIED_EVIDENCE'
        section_rows.append(dict(key=key,name=label,count=len(valid),status=status,latest_at=max((e['observed_at'] for e in valid),default=None),
                                 details=entry.get('details',{}) if verified else {}))
    count=sum(s['status']=='VERIFIED' for s in section_rows)
    table=catalog.standings(db,comp.id,fixture.season_id,cutoff)
    rows=table['rows'];top=rows[:2]
    games=verified_matches(db,comp.id,cutoff,season_id=fixture.season_id) if sport.name.casefold()=='football' else []
    meetings=[g for g in games if {g['home_id'],g['away_id']}=={fixture.home_name,fixture.away_name}][:5]
    def team(name):
        row=next((r for r in rows if r['club']==name),None)
        played=[g for g in games if name in (g['home_id'],g['away_id'])]
        scores=[(g['home_score'],g['away_score']) if g['home_id']==name else (g['away_score'],g['home_score']) for g in played]
        form=['W' if h>a else 'L' if h<a else 'D' for h,a in scores[:5]][::-1]
        return dict(name=name,standing=row,form=(row.get('form') if row else None) or form,
                    average_goals=round(sum(h for h,_ in scores)/len(scores),2) if scores else None,
                    clean_sheet_pct=round(sum(a==0 for _,a in scores)*100/len(scores),1) if scores else None,sample_size=len(scores))
    runtime=runtime_status(db)
    run=db.scalar(select(m.PipelineRun).where(m.PipelineRun.fixture_id==fixture.id).order_by(m.PipelineRun.updated_at.desc()).limit(1))
    stages={s.stage_key:s.status for s in db.scalars(select(m.PipelineStage).where(m.PipelineStage.run_id==run.id))} if run else {}
    authorized_sources={o.source_id for o in observations if (p:=providers.get(o.source_id)) and p.enabled and p.permission=='AUTHORIZED'}
    return dict(fixture=dict(id=fixture.id,home=fixture.home_name,away=fixture.away_name,kickoff_at=fixture.kickoff_at,status=fixture.status,
                             competition_id=comp.id,competition=comp.name,sport=sport.name,country=comp.country,season_id=fixture.season_id,season=season.label if season else None),
        cutoff=cutoff,dossier_id=dossier.id if dossier else None,version=dossier.version if dossier else None,
        status='VERIFIED' if count==len(SECTIONS) else 'INCOMPLETE',last_research_at=dossier.created_at if dossier else None,
        sections=section_rows,evidence=evidence,verified_sections=count,total_sections=len(SECTIONS),sample_limit=500,
        summary=dict(home=team(fixture.home_name),away=team(fixture.away_name),top_two=top,table_mode=table['mode'],table_warning=table.get('warning'),
                     head_to_head=[dict(id=g['id'],kickoff_at=g['kickoff'],home=g['home_id'],away=g['away_id'],home_score=g['home_score'],away_score=g['away_score']) for g in meetings]),
        metrics=dict(research_runs=db.scalar(select(func.count()).select_from(m.Research)) or 0,
                     fixtures_researched=db.scalar(select(func.count(func.distinct(m.Research.fixture_id)))) or 0,
                     evidence_items=db.scalar(select(func.count()).select_from(m.Observation).join(m.Source).where(m.Source.enabled.is_(True),m.Source.permission=='AUTHORIZED')) or 0),
        sources=dict(authorized=len(authorized_sources),recorded=len(providers),online=None),
        runtime=dict(status=runtime['status'],worker_online=runtime['worker_online'],next_run_at=runtime.get('next_run_at'),stages=stages),
        message='Coverage requires section-specific links to authorized pre-match evidence. Recorded observations alone do not establish verification. Statistics respect the fixture research cutoff.')


@router.get('/workspace/{fixture_id}')
def workspace(fixture_id:str,as_of:datetime|None=None):
    try:
        with SessionLocal() as db:return build_workspace(db,fixture_id,as_of)
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
