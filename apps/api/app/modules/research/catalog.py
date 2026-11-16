"""Season-scoped research views adapted from the supplied v3.0 module."""
from datetime import datetime, timezone
from sqlalchemy import select,case
from app.db import models as m
from app.modules.research.league import compute_table, verified_matches, utc


def cutoff_time(value=None):
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('as_of requires a timezone')
    if value > datetime.now(timezone.utc):
        raise ValueError('as_of cannot be in the future')
    return value


def competition_season(db, competition_id, season_id=None):
    competition = db.get(m.Competition, competition_id)
    if competition is None:
        raise LookupError('Competition not found')
    if season_id:
        season = db.get(m.CompetitionSeason, season_id)
        if season is None or season.competition_id != competition_id:
            raise ValueError('Season does not belong to this competition')
    return competition


def standings(db, competition_id, season_id=None, as_of=None, scope='overall'):
    if scope not in ('overall', 'home', 'away'):
        raise ValueError('Invalid standings scope')
    cutoff = cutoff_time(as_of)
    competition = competition_season(db, competition_id, season_id)
    # Scope and season must match exactly; overall rows are never relabelled as home/away.
    if season_id:
        snapshot = db.scalar(select(m.StandingsSnapshot).join(m.Source, m.Source.id == m.StandingsSnapshot.source_id)
            .where(m.StandingsSnapshot.competition_id == competition_id, m.StandingsSnapshot.season_id == season_id,
                   m.StandingsSnapshot.scope == scope, m.StandingsSnapshot.review_status == 'VERIFIED', m.StandingsSnapshot.captured_at <= cutoff,
                   m.StandingsSnapshot.verified_at <= cutoff, m.Source.enabled.is_(True), m.Source.permission == 'AUTHORIZED')
            .order_by(m.StandingsSnapshot.captured_at.desc(), m.StandingsSnapshot.verified_at.desc(), m.StandingsSnapshot.id).limit(1))
        if snapshot:
            source = db.get(m.Source, snapshot.source_id)
            return dict(mode='source_snapshot', scope=scope, season_id=season_id, as_of=cutoff,
                rows=sorted(snapshot.entries, key=lambda r: r['rank']),
                warning='Reviewed CSV-derived provisional standings; official deductions and tie-breakers are not included.' if snapshot.provenance.get('status')=='UNVERIFIED_COMPUTED' else None,
                source=dict(id=source.id, name=source.name, snapshot_id=snapshot.id, official=snapshot.official,
                    captured_at=snapshot.captured_at, verified_at=snapshot.verified_at,
                    source_url=snapshot.source_url, source_reference=snapshot.source_reference, content_hash=snapshot.content_hash, reviewed_by=snapshot.reviewed_by, review_status=snapshot.review_status, provenance=snapshot.provenance))
    # A separately labelled community cache is available without manual review.
    # It does not enter verified result, snapshot, research or prediction tables.
    from app.modules.standings.service import report as csv_report
    csv_table = csv_report(db, competition_id, season_id, cutoff, scope)
    if csv_table:
        return csv_table
    from app.modules.autonomy.community_tables import report as community_report
    community = community_report(db, competition_id, season_id, cutoff, scope)
    if community:
        return community
    sport = db.get(m.Sport, competition.sport_id)
    if scope != 'overall' or sport.name.lower() != 'football':
        return dict(mode='unavailable', scope=scope, season_id=season_id, as_of=cutoff, rows=[], source=None,
                    warning='No authorized, verified snapshot for this season and scope. Home/away rows are never inferred from overall standings.')
    matches = verified_matches(db, competition_id, cutoff, season_id=season_id)
    rows = compute_table(matches)
    for row in rows:
        row['club'] = row['team_id']
    warning = 'Unofficial computed table: 3/1/0 points, goal difference, then goals scored. Coverage, aliases and competition rules may affect ranks.'
    if not season_id:
        warning += ' All available seasons are combined; select a season for a season-specific table.'
    return dict(mode='computed_unofficial', scope=scope, season_id=season_id, as_of=cutoff, rows=rows,
                verified_matches=len(matches), source=None, warning=warning)


def fixtures(db, competition_id, season_id=None, limit=100):
    competition_season(db, competition_id, season_id)
    query = select(m.Fixture).where(m.Fixture.competition_id == competition_id)
    if season_id:
        query = query.where(m.Fixture.season_id == season_id)
    now=datetime.now(timezone.utc)
    rows = db.scalars(query.order_by(case((m.Fixture.kickoff_at>=now,0),else_=1),case((m.Fixture.kickoff_at>=now,m.Fixture.kickoff_at),else_=None).asc(),m.Fixture.kickoff_at.desc(), m.Fixture.id).limit(limit)).all()
    scores = {g['id']: g for g in verified_matches(db, competition_id, datetime.now(timezone.utc), season_id=season_id)}
    return [dict(id=f.id, competition_id=f.competition_id, season_id=f.season_id, kickoff=f.kickoff_at,
                 home=f.home_name, away=f.away_name, status='FINAL' if f.id in scores else f.status,
                 home_score=scores[f.id]['home_score'] if f.id in scores else None,
                 away_score=scores[f.id]['away_score'] if f.id in scores else None,
                 result_id=scores[f.id]['result_id'] if f.id in scores else None) for f in rows]


def dossier(db, fixture_id, as_of=None):
    fixture = db.get(m.Fixture, fixture_id)
    if fixture is None:
        raise LookupError('Fixture not found')
    cutoff = min(cutoff_time(as_of), utc(fixture.kickoff_at))
    observations = db.execute(select(m.Observation, m.Source).join(m.Source, m.Source.id == m.Observation.source_id)
        .where(m.Observation.fixture_id == fixture.id, m.Observation.observed_at < cutoff,
               m.Source.enabled.is_(True), m.Source.permission == 'AUTHORIZED')
        .order_by(m.Observation.observed_at.desc(), m.Observation.id).limit(200)).all()
    evidence = [dict(id=o.id, section=o.payload.get('section', 'fixture_provenance'), data=o.payload.get('data', o.payload),
                     source_id=s.id, source=s.name, source_url=o.source_url, content_hash=o.content_hash,
                     observed_at=o.observed_at, verification='AUTHORIZED_SOURCE_OBSERVATION') for o, s in observations]
    research = db.scalars(select(m.Research).where(m.Research.fixture_id == fixture.id, m.Research.created_at <= cutoff)
                         .order_by(m.Research.version.desc()).limit(20)).all()
    dossiers = [dict(id=r.id, version=r.version, status=r.status, sections=r.sections, evidence_ids=r.evidence_ids) for r in research]
    features = db.scalars(select(m.Feature).join(m.Research, m.Research.id == m.Feature.research_id)
        .where(m.Research.fixture_id == fixture.id, m.Research.created_at <= cutoff, m.Feature.cutoff_at < cutoff)
        .order_by(m.Feature.cutoff_at.desc()).limit(100)).all()
    forecasts = db.scalars(select(m.Prediction).where(m.Prediction.fixture_id == fixture.id, m.Prediction.predicted_at < cutoff)
                          .order_by(m.Prediction.predicted_at.desc()).limit(100)).all()
    return dict(fixture=dict(id=fixture.id, home=fixture.home_name, away=fixture.away_name, kickoff=fixture.kickoff_at,
                             competition_id=fixture.competition_id, season_id=fixture.season_id),
                cutoff=cutoff, evidence=evidence, dossiers=dossiers,
                features=[dict(id=f.id, research_id=f.research_id, cutoff_at=f.cutoff_at, features=f.features) for f in features],
                predictions=[dict(id=p.id, model_id=p.model_id, market_key=p.market_key, outcome_key=p.outcome_key,
                                  probability=float(p.probability), predicted_at=p.predicted_at) for p in forecasts],
                status='evidence_available' if evidence else 'awaiting_research',
                warning='Authorized observations are not independently verified dossiers or qualified predictions. Pre-match evidence is restricted to the requested cutoff and kickoff.')



def standings_coverage(db, competition_id, season_id, as_of=None):
    competition_season(db, competition_id, season_id)
    cutoff=cutoff_time(as_of)
    snapshots=db.scalars(select(m.StandingsSnapshot).join(m.Source,m.Source.id==m.StandingsSnapshot.source_id)
        .where(m.StandingsSnapshot.competition_id==competition_id,m.StandingsSnapshot.season_id==season_id,
               m.StandingsSnapshot.captured_at<=cutoff,m.Source.enabled.is_(True),m.Source.permission=='AUTHORIZED')
        .order_by(m.StandingsSnapshot.captured_at.desc(),m.StandingsSnapshot.id)).all()
    views={}
    for scope in ('overall','home','away'):
        rows=[r for r in snapshots if r.scope==scope]
        approved=[r for r in rows if r.review_status=='VERIFIED' and r.verified_at is not None and utc(r.verified_at)<=cutoff]
        pending=[r for r in rows if r.review_status=='PENDING_REVIEW' and utc(r.imported_at)<=cutoff]
        views[scope]=dict(status='VERIFIED' if approved else 'PENDING_REVIEW' if pending else 'MISSING',
            as_of=approved[0].captured_at if approved else pending[0].captured_at if pending else None,
            pending_count=len(pending),verified_count=len(approved))
    return dict(competition_id=competition_id,season_id=season_id,as_of=cutoff,views=views)


def standings_history(db, competition_id, season_id, scope='overall', before=None, limit=20):
    competition_season(db, competition_id, season_id)
    if scope not in ('overall','home','away'):
        raise ValueError('Invalid standings scope')
    cutoff=cutoff_time(before)
    records=db.execute(select(m.StandingsSnapshot,m.Source).join(m.Source,m.Source.id==m.StandingsSnapshot.source_id)
        .where(m.StandingsSnapshot.competition_id==competition_id,m.StandingsSnapshot.season_id==season_id,
               m.StandingsSnapshot.scope==scope,m.StandingsSnapshot.review_status=='VERIFIED',
               m.StandingsSnapshot.captured_at<=cutoff,m.StandingsSnapshot.verified_at<=cutoff,
               m.Source.enabled.is_(True),m.Source.permission=='AUTHORIZED')
        .order_by(m.StandingsSnapshot.captured_at.desc(),m.StandingsSnapshot.id).limit(limit)).all()
    return [dict(snapshot_id=s.id,as_of=s.captured_at,verified_at=s.verified_at,source_id=source.id,source=source.name,
                 source_url=s.source_url,reviewed_by=s.reviewed_by,official=s.official,provenance=s.provenance,
                 content_hash=s.content_hash) for s,source in records]
