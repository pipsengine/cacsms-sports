"""Countries are inferred only from unambiguous competition names; unknown feeds stay unspecified."""
from sqlalchemy import select
from app.db import models as m
from app.modules.autonomy.competition_country import infer_country, backfill
from test_browser_intelligence import factory as make_factory


def test_infers_unambiguous_countries_only():
    cases = {'Champions League 2026/2027': 'Europe', "UEFA Women's Champions League": 'Europe', 'Nations League 2026/27': 'Europe',
             'WM 2026 USA': 'International', 'LaLiga EA Sports 2026/2027': 'Spain', 'Premier League 2026/2027': 'England',
             'ADMIRAL Bundesliga Österreich': 'Austria', 'Fußball-Regionalliga Nord': 'Germany', 'NOFV-Oberliga Süd': 'Germany',
             '2. Bundesliga 2026/27 (Herren)': 'Germany', 'Thüringenliga': 'Germany',
             'Empty Stands Spendenliga 2026/2027': None, 'BLClaude': None, '??': None, 'Testspiele2026': None}
    assert {name: infer_country(name) for name in cases} == cases
    assert infer_country('Admiral', 'BLÖ') == 'Austria'


def test_backfill_sets_country_once_with_audit():
    session = make_factory()
    with session.begin() as db:
        sport = m.Sport(name='Football'); db.add(sport); db.flush()
        db.add_all([m.Competition(id='ucl', sport_id=sport.id, name='Champions League 2026/2027'),
                    m.Competition(id='junk', sport_id=sport.id, name='AgODMUSIC'),
                    m.Competition(id='be', sport_id=sport.id, name='Belgian Pro League', country='Belgium')])
    with session.begin() as db:
        assert backfill(db) == [{'competition': 'Champions League 2026/2027', 'country': 'Europe'}]
    with session.begin() as db:
        assert backfill(db) == []
        assert db.get(m.Competition, 'junk').country is None and db.get(m.Competition, 'be').country == 'Belgium'
        assert db.scalar(select(m.AuditEvent).where(m.AuditEvent.action == 'competition.country_inferred')).payload['method'] == 'NAME_RULES'
