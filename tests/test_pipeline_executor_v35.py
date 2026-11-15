import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'apps/api'))
from app.modules.pipeline.operations import match_analysis


def test_match_analysis_is_a_valid_distribution():
 result=match_analysis({'home_form':2.,'away_form':1.,'home_scoring_rate':2.,'away_scoring_rate':1.,'home_conceding_rate':1.,'away_conceding_rate':2.})
 assert result['expected_score']=={'home':2.0,'away':1.0}
 assert abs(sum(result['outcome_probabilities'].values())-1)<1e-4
 assert result['outcome_probabilities']['HOME']>result['outcome_probabilities']['AWAY']
 assert result['matchup']['assessment']=='HOME_ADVANTAGE'
 assert 0<result['over_2_5']<1 and 0<result['both_teams_score']<1


def test_match_analysis_handles_zero_rates():
 result=match_analysis({k:0. for k in ('home_form','away_form','home_scoring_rate','away_scoring_rate','home_conceding_rate','away_conceding_rate')})
 assert result['outcome_probabilities']['DRAW']==1.0 and result['matchup']['assessment']=='BALANCED'
