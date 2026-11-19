from datetime import datetime,timedelta,timezone,date
import pytest
from sqlalchemy import create_engine,select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.db.base import Base
from app.db import models as m
from app.modules.research import deep_workspace_routes as deep


@pytest.fixture
def store():
    engine=create_engine('sqlite://',poolclass=StaticPool,connect_args={'check_same_thread':False},execution_options={'schema_translate_map':{s:None for s in {t.schema for t in Base.metadata.tables.values()}}})
    Base.metadata.create_all(engine);factory=sessionmaker(bind=engine)
    at=datetime.now(timezone.utc)-timedelta(hours=1)
    with factory.begin() as db:
        db.add(m.Sport(id='sport',name='Football'));db.flush()
        db.add(m.Competition(id='league',sport_id='sport',name='League',country='Germany'));db.flush()
        db.add(m.CompetitionSeason(id='season',competition_id='league',label='2026/27',start_date=date(2026,7,1),end_date=date(2027,6,30)));db.flush()
        db.add(m.Source(id='source',name='Authorized Source',enabled=True,permission='AUTHORIZED'))
        db.add_all([m.Fixture(id='fixture',competition_id='league',season_id='season',home_name='Home',away_name='Away',kickoff_at=at+timedelta(days=1)),m.Fixture(id='other',competition_id='league',season_id='season',home_name='Other',away_name='Away',kickoff_at=at+timedelta(days=1))]);db.flush()
        ids=[];sections={}
        for i,key in enumerate(deep.SECTIONS):
            ident='obs'+str(i);ids.append(ident)
            db.add(m.Observation(id=ident,source_id='source',fixture_id='fixture',observed_at=at,source_url='https://provider.example/evidence',content_hash=ident.ljust(64,'0'),payload={'section':key,'data':{'fact':key}}))
            sections[key]={'status':'VERIFIED','evidence_ids':[ident],'details':{'reviewed':True}}
        db.add(m.Research(id='dossier',fixture_id='fixture',version=1,status='VERIFIED',sections=sections,evidence_ids=ids,created_at=at+timedelta(minutes=1)))
    yield factory,at
    engine.dispose()


def test_canonical_section_mapping_and_counts(store):
    factory,at=store
    with factory() as db:
        report=deep.build_workspace(db,'fixture')
        assert report['verified_sections']==7 and report['total_sections']==7 and report['status']=='VERIFIED'
        assert all(s['count']==1 for s in report['sections'])
        assert report['metrics']['research_runs']==1
        assert report['sources']==dict(authorized=1,recorded=1,online=None)
        assert report['summary']['top_two']==[]
        assert report['summary']['home']['average_goals'] is None
        assert deep.section_key('Probable lineups')=='lineups'
        assert deep.section_key('Head-to-head')=='head_to_head'
        assert deep.section_key('Official Results')=='official_result'
        assert [s['name'] for s in report['sections']][5]=='Official Results'


def test_links_require_same_section_fixture_and_authorized_source(store):
    factory,at=store
    with factory.begin() as db:
        dossier=db.get(m.Research,'dossier')
        sections=dict(dossier.sections);sections['head_to_head']={'status':'VERIFIED','evidence_ids':['obs1']}
        dossier.sections=sections
        db.get(m.Observation,'obs2').fixture_id='other'
    with factory() as db:
        report=deep.build_workspace(db,'fixture')
        assert report['verified_sections']==5 and report['status']=='INCOMPLETE'
    with factory.begin() as db:db.get(m.Source,'source').enabled=False
    with factory() as db:
        report=deep.build_workspace(db,'fixture')
        assert report['verified_sections']==0
        assert all(e['data'] is None for e in report['evidence'])


def test_verified_section_loses_verification_when_one_required_source_is_revoked(store):
    factory,at=store
    with factory.begin() as db:
        db.add(m.Source(id='second',name='Second source',enabled=True,permission='AUTHORIZED'))
        db.add(m.Observation(id='second-form',source_id='second',fixture_id='fixture',observed_at=at,
            content_hash='s'*64,payload={'section':'recent_form','data':{'fact':'recent_form'}}))
        dossier=db.get(m.Research,'dossier')
        dossier.evidence_ids=[*dossier.evidence_ids,'second-form']
        dossier.sections={**dossier.sections,'recent_form':{'status':'VERIFIED','evidence_ids':['obs1','second-form']}}
    with factory() as db:
        assert next(s for s in deep.build_workspace(db,'fixture')['sections'] if s['key']=='recent_form')['status']=='VERIFIED'
    with factory.begin() as db:db.get(m.Source,'second').enabled=False
    with factory() as db:
        row=next(s for s in deep.build_workspace(db,'fixture')['sections'] if s['key']=='recent_form')
        assert row['status']=='PROVISIONAL' and row['count']==1


def test_prematch_cutoff_does_not_leak_later_evidence_or_dossiers(store):
    factory,at=store
    with factory.begin() as db:
        db.get(m.Fixture,'fixture').kickoff_at=at-timedelta(hours=1)
        db.add(m.StandingsSnapshot(competition_id='league',season_id='season',source_id='source',source_url='https://provider.example/table',source_reference='late',content_hash='s'*64,captured_at=at,verified_at=at,review_status='VERIFIED',entries=[dict(rank=1,club='Home',points=30)]))
    with factory() as db:
        report=deep.build_workspace(db,'fixture')
        assert report['evidence']==[] and report['dossier_id'] is None
        assert report['summary']['top_two']==[] and report['summary']['home']['standing'] is None


def test_endpoint_validation_and_read_only(store,monkeypatch):
    factory,at=store;monkeypatch.setattr(deep,'SessionLocal',factory)
    app=FastAPI();app.include_router(deep.router);client=TestClient(app)
    assert client.get('/api/v1/sports/research/workspace/fixture').status_code==200
    assert client.get('/api/v1/sports/research/workspace/missing').status_code==404
    assert client.get('/api/v1/sports/research/workspace/fixture?as_of=2099-01-01T00:00:00Z').status_code==422
    assert client.post('/api/v1/sports/research/workspace/fixture').status_code==405


def test_partial_evidence_and_league_context_are_not_verified(store):
    factory,at=store
    with factory.begin() as db:
        db.add(m.Observation(id='partial',source_id='source',fixture_id='other',observed_at=at,
            content_hash='p'*64,payload={'section':'team_recent_results','verification':'SINGLE_SOURCE',
            'data':{'side':'home','team':'Other','results':[{'kickoff_at':(at-timedelta(days=45)).isoformat()}]}}))
        db.add(m.ProviderSyncState(id='table',source_id='source',last_full_at=at,payload={
            'competition_id':'league','season_id':'season','standings_url':'https://provider.example/table',
            'community_tables':{'overall':[dict(club='Home',rank=1,points=3)]}}))
    with factory() as db:
        report=deep.build_workspace(db,'other')
        sections={row['key']:row for row in report['sections']}
        assert sections['recent_form']['status']=='STALE' and sections['recent_form']['recorded_count']==1
        assert sections['recent_form']['count']==0 and report['evidence'][0]['freshness']=='STALE'
        assert sections['standings']['status']=='PROVISIONAL' and sections['standings']['context_source']['name']=='Authorized Source'
        assert report['verified_sections']==0 and report['dossier_id'] is None
    with factory.begin() as db:db.get(m.Source,'source').enabled=False
    with factory() as db:
        sections={row['key']:row for row in deep.build_workspace(db,'other')['sections']}
        assert sections['recent_form']['status']=='NO_VERIFIED_EVIDENCE'
        assert sections['standings']['status']=='NO_VERIFIED_EVIDENCE'


def test_matchday_is_reported_only_when_recorded(store):
    factory,at=store
    with factory() as db:assert deep.build_workspace(db,'fixture')['fixture']['matchday'] is None
    with factory.begin() as db:db.get(m.Fixture,'fixture').matchday=28
    with factory() as db:assert deep.build_workspace(db,'fixture')['fixture']['matchday']==28


def test_provider_round_maps_to_matchday():
    from app.modules.autonomy.openligadb import normalize
    match=lambda ident,group:{'matchID':ident,'matchDateTimeUTC':'2027-03-14T16:30:00Z','team1':{'teamName':'Home'},'team2':{'teamName':'Away'},'group':group}
    rows,_,_=normalize([match(1,{'groupOrderID':28}),match(2,None),match(3,{'groupOrderID':'x'})],datetime(2027,3,1,tzinfo=timezone.utc))
    assert [r['matchday'] for r in rows]==[28,None,None]
