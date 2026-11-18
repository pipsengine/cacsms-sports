"""Standings package API, using shared canonical records and existing admin auth."""
from datetime import datetime,timezone
from fastapi import APIRouter,HTTPException,Header,Query
from pydantic import BaseModel,Field,ConfigDict
from sqlalchemy import select,func
from app.db import models as m
from app.db.base import SessionLocal
from app.modules.results.routes import admin_only
from app.modules.research import catalog,catalog_routes
from app.modules.standings import service

router=APIRouter(prefix='/api/v1/sports/standings',tags=['Standings acquisition'])


def read(action):
    try:
        with SessionLocal() as db:return action(db)
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    except PermissionError as exc:raise HTTPException(403,str(exc)) from exc
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc


def identity(db,ident,season=None):
    comp=db.get(m.Competition,ident)
    if comp is None:
        state=service.resolve_state(db,ident);comp=db.get(m.Competition,state.payload['competition_id'])
    if comp is None:raise LookupError('Unknown competition')
    sid=None
    if season:
        item=db.get(m.CompetitionSeason,season)
        if item is None:
            year=service.season_year(season)
            item=db.scalar(select(m.CompetitionSeason).where(m.CompetitionSeason.competition_id==comp.id,m.CompetitionSeason.label.in_([season,f'{year}/{year+1}',f'{year}/{str(year+1)[-2:]}'])))
        if item is None or item.competition_id!=comp.id:raise ValueError('Season does not belong to this competition')
        sid=item.id
    return comp,sid


class Register(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    id:str=Field(pattern=r'^[a-zA-Z0-9_-]{2,48}$')
    sport:str='Football'
    country:str=Field(min_length=1,max_length=100)
    name:str=Field(min_length=1,max_length=150)
    division_code:str=Field(pattern=r'^[A-Za-z0-9]{1,12}$')
    source_url:str=Field(max_length=800)
    authorized:bool=False
    points_win:int=Field(default=3,ge=2,le=3)


class SyncRequest(BaseModel):
    season:str


@router.post('/admin/competitions',status_code=201)
def register(body:Register,x_admin_token:str|None=Header(default=None)):
    admin_only(x_admin_token)
    try:
        with SessionLocal.begin() as db:return service.register(db,body.model_dump())
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc


@router.post('/admin/sync/{competition_id}')
def sync(competition_id:str,body:SyncRequest,x_admin_token:str|None=Header(default=None)):
    admin_only(x_admin_token)
    try:return service.sync(SessionLocal,competition_id,body.season)
    except LookupError as exc:raise HTTPException(404,str(exc)) from exc
    except PermissionError as exc:raise HTTPException(403,str(exc)) from exc
    except ValueError as exc:raise HTTPException(422,str(exc)) from exc
    except Exception as exc:raise HTTPException(502,'Acquisition failed; inspect synchronization history') from exc


@router.get('/sports')
def sports():return catalog_routes.sports()


@router.get('/countries')
def countries(sport:str='Football'):return catalog_routes.countries(sport)


@router.get('/competitions')
def competitions(sport:str='Football',country:str|None=None):return catalog_routes.leagues(sport,country)


@router.get('/seasons')
def seasons(competition_id:str):
    def load(db):
        comp,_=identity(db,competition_id)
        return [dict(id=s.id,label=s.label,is_current=s.is_current) for s in db.scalars(select(m.CompetitionSeason).where(m.CompetitionSeason.competition_id==comp.id).order_by(m.CompetitionSeason.start_date.desc()))]
    return read(load)


def table_report(db,competition_id,season,mode,as_of):
    comp,sid=identity(db,competition_id,season)
    report=catalog.standings(db,comp.id,sid,as_of,mode)
    return comp,sid,report


@router.get('/table')
def table(competition_id:str,season:str|None=None,mode:str='overall',as_of:datetime|None=None,page:int=Query(1,ge=1),page_size:int=Query(100,ge=1,le=100),all_rows:bool=False):
    def load(db):
        comp,sid,r=table_report(db,competition_id,season,mode,as_of)
        aliases={'P':'played','W':'wins','D':'draws','L':'losses','GF':'goals_for','GA':'goals_against','GD':'goal_difference','Pts':'points'}
        rows=[{**row,**{a:row.get(k) for a,k in aliases.items()}} for row in r['rows']]
        return {**r,'classification':r['mode'],'mode':mode,'competition':{'id':comp.id,'name':comp.name,'country':comp.country},'season':sid,'official':bool(r.get('source') and r['source']['official']),
                'method':r.get('warning'),'total_teams':len(rows),'page':1 if all_rows else page,'page_size':len(rows) if all_rows else page_size,'rows':rows if all_rows else rows[(page-1)*page_size:page*page_size]}
    return read(load)


@router.get('/top-two')
def top_two(competition_id:str,season:str|None=None,as_of:datetime|None=None):
    def load(db):
        comp,sid,r=table_report(db,competition_id,season,'overall',as_of)
        return {'competition_id':comp.id,'season':sid,'official':bool(r.get('source') and r['source']['official']),'clubs':r['rows'][:2],'warning':r.get('warning')}
    return read(load)


@router.get('/analytics')
def analytics(competition_id:str,season:str|None=None,as_of:datetime|None=None):
    def load(db):
        comp,sid,r=table_report(db,competition_id,season,'overall',as_of)
        sport=db.get(m.Sport,comp.sport_id)
        if sport.name.casefold()!='football':
            return {'competition_id':comp.id,'season':sid,'classification':r['mode'],'sample_size':0,'average_goals':None,
                    'home_win_pct':None,'draw_pct':None,'away_win_pct':None,'goals_by_matchday':None,'goals_by_date':[],
                    'note':'Football-specific goal and draw analytics are unavailable for this sport.'}
        stats=r.get('community_statistics')
        if stats:
            n=stats['matches'];h=stats['home_wins'];a=stats['away_wins'];d=stats['draws']
            matches=sum(row['played'] for row in r['rows'])/2
            average=sum(row['goals_for'] for row in r['rows'])/matches if matches else None
            trends=stats.get('goals_trend',[])
        else:
            cutoff=catalog.cutoff_time(as_of)
            from app.modules.research.league import verified_matches
            games=verified_matches(db,comp.id,cutoff,season_id=sid);n=len(games)
            h=sum(g['home_score']>g['away_score'] for g in games);a=sum(g['home_score']<g['away_score'] for g in games);d=n-h-a
            average=sum(g['home_score']+g['away_score'] for g in games)/n if n else None
            dates={}
            for game in games:dates.setdefault(game['kickoff'].date().isoformat(),[]).append(game['home_score']+game['away_score'])
            trends=[{'day':day,'value':sum(scores)/len(scores)} for day,scores in sorted(dates.items())[-5:]]
        return {'competition_id':comp.id,'season':sid,'classification':r['mode'],'sample_size':n,'average_goals':round(average,3) if average is not None else None,
                'home_win_pct':round(h*100/n,2) if n else None,'draw_pct':round(d*100/n,2) if n else None,'away_win_pct':round(a*100/n,2) if n else None,
                'goals_by_matchday':None,'goals_by_date':trends,'note':'A date trend is not a matchday trend; reliable round identifiers are unavailable.'}
    return read(load)


@router.get('/history')
def history(competition_id:str,season:str|None=None,as_of:datetime|None=None):
    def load(db):
        comp,sid=identity(db,competition_id,season);cutoff=catalog.cutoff_time(as_of)
        rows=db.scalars(select(m.AuditEvent).where(m.AuditEvent.action=='standings.sync',m.AuditEvent.correlation_id==comp.id,m.AuditEvent.created_at<=cutoff).order_by(m.AuditEvent.created_at.desc()).limit(100))
        label=db.get(m.CompetitionSeason,sid).label if sid else None
        items=[]
        for row in rows:
            if label and service.season_year(row.payload['season'])!=service.season_year(label):continue
            items.append({'id':row.id,**row.payload})
        return {'competition_id':comp.id,'season':sid,'syncs':items[:30]}
    return read(load)


@router.get('/health')
def health(competition_id:str):
    def load(db):
        comp,_=identity(db,competition_id)
        states=list(db.scalars(select(m.ProviderSyncState).where(m.ProviderSyncState.payload['competition_id'].as_string()==comp.id)))
        authorized=[s for s in states if (source:=db.get(m.Source,s.source_id)) and source.enabled and source.permission=='AUTHORIZED']
        success=[s for s in authorized if s.last_full_at]
        from app.modules.autonomy.fixture_discovery import enabled as discovery_enabled
        nexts=[s.next_check_at for s in authorized if s.next_check_at and not (discovery_enabled() and s.id.startswith('openligadb:'))]
        failures=sum(s.failures or 0 for s in authorized)
        errors=[s.payload['table_error'] for s in authorized if (s.payload or {}).get('table_error')]
        return {'engine':'standings','status':'FAILED' if failures else 'DATA_AVAILABLE' if success else 'WAITING_FOR_DATA','source_count':len(states),'authorized_sources':len(authorized),
                'last_successful_sync':max((s.last_full_at for s in success),default=None),'next_sync':min(nexts,default=None),
                'source_online':None,'data_quality_score':None,'failures':failures,'errors':errors,'note':'Source authorization and recorded syncs do not prove current reachability or data quality.'}
    return read(load)
