from app.modules.operations.service import STATES
from app.modules.research.service import SECTIONS,VALID

def test_mission_states_fail_closed():
    assert 'RUNNING' not in STATES['COMPLETED']
    assert 'COMPLETED' not in STATES['PENDING']
    assert 'CANCELLED' in STATES['RUNNING']

def test_research_sections():
    assert 'lineups' in SECTIONS and 'match_statistics' in SECTIONS
    assert 'UNVERIFIED' not in VALID
