from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select,func
from app.db import models as m
from app.modules.research import evidence_bridge as bridge,deep_workspace_routes as deep
from app.modules.research.service import SECTIONS,build_dossier
from app.modules.match_analysis import service as match_analysis
from app.modules.pipeline.operations import research,analyse,Waiting
from test_fixture_discovery import store,AT
from test_research_evidence_bridge import collect


@pytest.mark.parametrize('sport,unit,average', [('Football','goals',2),('Basketball','points',91),
    ('Ice Hockey','goals',2),('Tennis','provider score units',2),('Table Tennis','provider score units',2)])
def test_collected_histories_reach_sport_specific_summaries_without_verification(store,sport,unit,average):
    fixture_id=collect(store,sport)
    at=AT+timedelta(seconds=12)
    with store.begin() as db:
        with pytest.raises(Waiting):research(db,SimpleNamespace(fixture_id=fixture_id),at)
        report=deep.build_workspace(db,fixture_id,at)
        assert report['research_readiness']['research_adapter'] is True
        assert 'no implemented' not in report['research_readiness']['reason']
        assert report['sport_profile']['score_unit']==unit
        for side in ('home','away'):
            team=report['summary'][side]
            assert team['sample_size']==1 and team['basis']=='PROVISIONAL_SAMPLE'
            assert team['form']==['W'] and team['average_score']==average
            assert team['source_name'] and team['evidence_ids']
            if unit!='goals':assert team['average_goals'] is None and team['clean_sheet_pct'] is None
        assert report['verified_sections']==0
        assert next(row for row in report['sections'] if row['key']=='match_statistics')['status']=='PROVISIONAL'
        derived=[o for o in db.scalars(select(m.Observation)) if o.payload.get('producer')==bridge.PRODUCER]
        if sport!='Football':
            assert all('home_form' not in o.payload['data'] and 'home_scoring_rate' not in o.payload['data'] for o in derived)
        analysis=match_analysis.workspace(db,fixture_id,at)
        assert analysis['expected_goals'] is None
        assert all(row['basis']=='PROVISIONAL_SAMPLE' for row in analysis['form_metrics'])
        assert all(row['status']!='VERIFIED' for row in analysis['summary'])
        assert not db.scalar(select(func.count()).select_from(m.Prediction))


def test_merge_captures_deduplicates_matches_and_keeps_actual_provenance():
    one=SimpleNamespace(id='one',observed_at=AT)
    two=SimpleNamespace(id='two',observed_at=AT+timedelta(seconds=4))
    row={'kickoff_at':(AT-timedelta(days=2)).isoformat(),'home':'home','away':'opponent','home_score':91,'away_score':86}
    older={**row,'kickoff_at':(AT-timedelta(days=5)).isoformat()}
    parent,rows,ids=bridge.merge_samples([(two,[row]),(one,[row,older])])
    assert parent.id=='two' and len(rows)==2 and set(ids)=={'one','two'}
    with pytest.raises(ValueError,match='Conflicting provider scores'):
        bridge.merge_samples([(one,[row]),(two,[{**row,'home_score':92}])])


def test_verified_basketball_features_use_descriptive_scores_not_football_poisson(store):
    fixture_id=collect(store,'Basketball')
    at=AT+timedelta(seconds=12)
    with store.begin() as db:
        sections={key:{'status':'UNAVAILABLE','evidence_ids':[]} for key in SECTIONS}
        ids=[]
        for section,data in [('recent_form',{'home_win_rate':60,'away_win_rate':40}),
                             ('match_statistics',{'home_average_score':110,'away_average_score':100,'home_average_conceded':105,'away_average_conceded':108})]:
            obs=m.Observation(source_id=bridge.SPORTSDB_ID,fixture_id=fixture_id,observed_at=at-timedelta(seconds=1),
                content_hash=section.ljust(64,'x'),payload={'section':section,'data':{'sport':'Basketball',**data},'verification':'INDEPENDENT_REVIEW','reviewer':'controlled-test-reviewer'})
            db.add(obs);db.flush();ids.append(obs.id)
            sections[section]={'status':'VERIFIED','evidence_ids':[obs.id]}
        dossier=build_dossier(db,fixture_id,sections,ids,at=at)
        run=m.PipelineRun(fixture_id=fixture_id,idempotency_key='basketball-analysis-test')
        db.add(run);db.flush()
        receipt=analyse(db,run,at)
        feature=db.get(m.Feature,receipt.details['feature_id'])
        assert feature.features['sport']=='Basketball'
        assert feature.features['sport_features']['home_average_score']==110
        assert 'numeric_features' not in feature.features
        assert feature.features['analysis']=={'method':'DESCRIPTIVE_VERIFIED_SPORT_SCORES','score_unit':'points','average_score_difference':10}
        assert not db.scalar(select(func.count()).select_from(m.Prediction))
