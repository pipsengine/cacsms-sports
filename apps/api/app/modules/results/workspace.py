"""Correction-aware, read-only results workspace over existing platform tables."""
from collections import Counter
from datetime import datetime, timezone
from sqlalchemy import select, func, and_
from app.db import models as m
from app.modules.results.service import performance_summary


def current_results():
    versions = select(m.Result.fixture_id, func.max(m.Result.version).label('version')).group_by(m.Result.fixture_id).subquery()
    return select(m.Result).join(versions, and_(m.Result.fixture_id == versions.c.fixture_id, m.Result.version == versions.c.version))


def latest_settlement_rows(db):
    """Only settlements belonging to the fixture's current result are effective."""
    ids = current_results().with_only_columns(m.Result.id)
    return db.execute(select(m.Settlement, m.Prediction, m.Result)
                      .join(m.Prediction, m.Settlement.prediction_id == m.Prediction.id)
                      .join(m.Result, m.Settlement.result_id == m.Result.id)
                      .where(m.Result.id.in_(ids)).order_by(m.Result.verified_at.desc(), m.Prediction.id)).all()


def workspace(db):
    results = db.scalars(current_results().order_by(m.Result.verified_at.desc())).all()
    result_by_fixture = {r.fixture_id: r for r in results}
    effective = latest_settlement_rows(db)
    outcomes = Counter(s.outcome for s, _, _ in effective)
    quality = performance_summary([(float(p.probability), s.outcome) for s, p, _ in effective])
    predictions = db.scalars(select(m.Prediction).order_by(m.Prediction.predicted_at.desc(), m.Prediction.id)).all()
    fixtures = {f.id: f for f in db.scalars(select(m.Fixture)).all()}
    competitions = {c.id: c for c in db.scalars(select(m.Competition)).all()}
    sports = {s.id: s.name for s in db.scalars(select(m.Sport)).all()}
    settled = {p.id: s for s, p, _ in effective}
    evidence = db.execute(select(m.ResultEvidence, m.Source, m.Observation)
                          .join(m.Source, m.ResultEvidence.source_id == m.Source.id)
                          .join(m.Observation, m.ResultEvidence.observation_id == m.Observation.id)
                          .where(m.ResultEvidence.result_id.in_([r.id for r in results]))).all()
    evidence_by_result = {}
    for link, source, observation in evidence:
        evidence_by_result.setdefault(link.result_id, []).append({'source': source.name, 'source_url': observation.source_url,
                                                                 'sha256': observation.content_hash, 'observed_at': observation.observed_at.isoformat()})
    def identity(f):
        c = competitions.get(f.competition_id)
        return {'fixture_id': f.id, 'fixture': f'{f.home_name} vs {f.away_name}', 'kickoff_at': f.kickoff_at.isoformat(),
                'sport': sports.get(c.sport_id) if c else None, 'competition': c.name if c else None}
    register = []
    for r in results:
        f = fixtures.get(r.fixture_id)
        if not f:
            continue
        score = r.outcome.get('score') or {}
        register.append({'id': r.id, **identity(f), 'version': r.version, 'verified_at': r.verified_at.isoformat(),
                         'score': f"{score['home']} – {score['away']}" if 'home' in score and 'away' in score else None,
                         'status': r.outcome.get('status'), 'outcomes': r.outcome.get('outcomes'),
                         'evidence': evidence_by_result.get(r.id, [])})
    settlements = []
    exceptions = []
    now = datetime.now(timezone.utc)
    for p in predictions:
        f = fixtures.get(p.fixture_id)
        if not f:
            continue
        result = result_by_fixture.get(p.fixture_id)
        settlement = settled.get(p.id)
        row = {'id': p.id, **identity(f), 'market': p.market_key, 'selection': p.outcome_key,
               'probability': float(p.probability), 'outcome': settlement.outcome if settlement else 'PENDING',
               'result_version': result.version if result else None, 'verified_at': result.verified_at.isoformat() if result else None}
        settlements.append(row)
        kickoff = f.kickoff_at if f.kickoff_at.tzinfo else f.kickoff_at.replace(tzinfo=timezone.utc)
        reason = ('UNRESOLVED_MARKET' if settlement and settlement.outcome == 'UNRESOLVED' else
                  'AWAITING_SETTLEMENT' if result and not settlement else
                  'AWAITING_OFFICIAL_RESULT' if not result and kickoff <= now else None)
        if reason:
            exceptions.append({**row, 'reason': reason, 'fixture_status': f.status})
    events = db.scalars(select(m.AuditEvent).where(m.AuditEvent.action.like('result.%'))
                        .order_by(m.AuditEvent.created_at.desc(), m.AuditEvent.id).limit(100)).all()
    sources = sorted({entry['source'] for entries in evidence_by_result.values() for entry in entries})
    return {'mode': 'PAPER', 'observed_at': now.isoformat(), 'summary': {
                'verified_matches': len(results), 'settled_forecasts': sum(outcomes.get(k, 0) for k in ('WON', 'LOST', 'VOID', 'PUSH')),
                'wins': outcomes['WON'], 'losses': outcomes['LOST'], 'voids': outcomes['VOID'], 'pushes': outcomes['PUSH'],
                'unresolved': outcomes['UNRESOLVED'], 'pending': len(predictions)-len(effective),
                'corrected_matches': sum(r.version > 1 for r in results), 'roi': None, **{'quality': quality}},
            'register': register, 'settlements': settlements, 'exceptions': exceptions,
            'reconciliation': {'forecast_count': len(predictions), 'current_settlement_count': len(effective),
                               'missing_current_settlements': sum(bool(result_by_fixture.get(p.fixture_id)) and p.id not in settled for p in predictions),
                               'results_with_evidence': sum(bool(evidence_by_result.get(r.id)) for r in results),
                               'verified_results': len(results), 'ticket_reconciliation': 'NOT_MEASURED'},
            'acquisition': {'sources': sources, 'last_verified_at': max((r.verified_at.isoformat() for r in results), default=None),
                            'reconciliation_interval_seconds': 300, 'scheduler_status': 'NOT_OBSERVED', 'next_sync': None},
            'learning': {'scored_forecasts': quality['settled_forecasts'], 'status': quality['status'],
                         'retraining': 'NOT_SCHEDULED_BY_RESULTS', 'automatic_deployment': False,
                         'note': 'Verified outcomes are available for descriptive model monitoring. No retraining queue is recorded.'},
            'audit': [{'id': e.id, 'at': e.created_at.isoformat(), 'actor': e.actor, 'event': e.action, 'detail': e.payload} for e in events]}
