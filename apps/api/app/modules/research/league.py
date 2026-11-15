"""Adapted from the supplied 2.9 scaffold to existing versioned result evidence."""
from collections import defaultdict
from datetime import datetime, timezone
from sqlalchemy import select
from app.db import models as m

def compute_table(matches):
    table = defaultdict(lambda: dict(played=0, wins=0, draws=0, losses=0, goals_for=0, goals_against=0, points=0))
    for match in matches:
        h, a, hg, ag = match['home_id'], match['away_id'], match['home_score'], match['away_score']
        if h == a or hg is None or ag is None or hg < 0 or ag < 0:
            continue
        for team, gf, ga in ((h, hg, ag), (a, ag, hg)):
            row = table[team]
            row['played'] += 1
            row['goals_for'] += gf
            row['goals_against'] += ga
            row['wins' if gf > ga else 'losses' if gf < ga else 'draws'] += 1
            row['points'] += 3 if gf > ga else 1 if gf == ga else 0
    result = []
    for team_id, row in table.items():
        result.append(dict(team_id=team_id, **row, goal_difference=row['goals_for']-row['goals_against']))
    # Default ranking; official competitions may use H2H, deductions or playoffs.
    result.sort(key=lambda x: (-x['points'], -x['goal_difference'], -x['goals_for'], str(x['team_id'])))
    for rank, row in enumerate(result, 1):
        row['computed_rank'] = rank
    return result



def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def top_two_research(db, competition_id, as_of=None, recent=5, since=None):
    cutoff = as_of or datetime.now(timezone.utc)
    if cutoff.tzinfo is None or (since is not None and since.tzinfo is None):
        raise ValueError('as_of and since must include timezone')
    if not 1 <= recent <= 20:
        raise ValueError('recent must be between 1 and 20')
    if since is not None and since >= cutoff:
        raise ValueError('since must precede as_of')
    competition = db.get(m.Competition, competition_id)
    if competition is None:
        raise LookupError('Competition not found')
    sport = db.get(m.Sport, competition.sport_id)
    if sport is None or sport.name.lower() != 'football':
        raise ValueError('Computed football standings are not valid for this sport')
    # Select the latest version known at the cutoff BEFORE validating its score.
    # Invalid corrections must never cause fallback to a superseded score.
    records = db.execute(select(m.Fixture, m.Result).join(m.Result, m.Result.fixture_id == m.Fixture.id)
        .where(m.Fixture.competition_id == competition_id, m.Fixture.kickoff_at < cutoff,
               m.Result.verified_at <= cutoff).order_by(m.Result.version.desc())).all()
    latest = {}
    for fixture, result in records:
        latest.setdefault(fixture.id, (fixture, result))
    matches = []
    for fixture, result in latest.values():
        if since is not None and utc(fixture.kickoff_at) < since:
            continue
        score = result.outcome.get('score', {})
        if result.outcome.get('status') != 'FINAL' or not isinstance(score, dict):
            continue
        hg, ag = score.get('home'), score.get('away')
        if type(hg) is not int or type(ag) is not int or min(hg, ag) < 0 or fixture.home_name == fixture.away_name:
            continue
        evidence = db.execute(select(m.ResultEvidence, m.Observation, m.Source)
            .join(m.Observation, m.Observation.id == m.ResultEvidence.observation_id)
            .join(m.Source, m.Source.id == m.ResultEvidence.source_id)
            .where(m.ResultEvidence.result_id == result.id)).all()
        valid = [e.id for e, o, s in evidence if s.enabled and s.permission == 'AUTHORIZED'
                 and o.source_id == s.id and o.fixture_id == fixture.id
                 and utc(o.observed_at) <= utc(result.verified_at) and utc(result.verified_at) >= utc(fixture.kickoff_at)]
        if not valid:
            continue
        matches.append(dict(id=fixture.id, home_id=fixture.home_name, away_id=fixture.away_name,
            home_score=hg, away_score=ag, kickoff=utc(fixture.kickoff_at), result_id=result.id,
            result_version=result.version, evidence_ids=valid))
    matches.sort(key=lambda x: (x['kickoff'], x['id']), reverse=True)
    leaders = compute_table(matches)[:2]
    for row in leaders:
        games = [g for g in matches if row['team_id'] in (g['home_id'], g['away_id'])][:recent]
        form = []
        for g in reversed(games):
            gf, ga = (g['home_score'], g['away_score']) if row['team_id'] == g['home_id'] else (g['away_score'], g['home_score'])
            form.append('W' if gf > ga else 'D' if gf == ga else 'L')
        row.update(club=row['team_id'], last_matches_form=''.join(form), recent_matches_count=len(games))
    ids = {r['team_id'] for r in leaders}
    h2h = [dict(fixture_id=g['id'], kickoff=g['kickoff'].isoformat(), home_id=g['home_id'], away_id=g['away_id'],
                home_score=g['home_score'], away_score=g['away_score'], result_id=g['result_id'],
                result_version=g['result_version'], evidence_ids=g['evidence_ids'])
           for g in matches if len(ids) == 2 and {g['home_id'], g['away_id']} == ids][:recent]
    return dict(competition=dict(id=competition.id, name=competition.name, country=competition.country),
        as_of=cutoff.isoformat(), since=since.isoformat() if since else None, verified_matches=len(matches),
        top_two=leaders, head_to_head=h2h, qualified=False, mode='PAPER',
        method='3/1/0 points; goal difference then goals scored; club name breaks remaining ties',
        limitations=['Computed research, not official standings; deductions and competition-specific rules are excluded',
                     'Incomplete coverage and club-name aliases affect rankings',
                     'Use since to restrict the season; otherwise all available history is included',
                     'Current source authorization is required, including for historical queries'],
        status='research_only' if len(leaders) == 2 else 'insufficient_data')
