"""Read-only analytics for pre-match forecast cohorts and current result versions."""
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select, or_
from app.db import models as m
from app.modules.results.workspace import latest_settlement_rows
from engines.learning.monitor import score_window


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def metrics(records):
    counts = Counter(r['outcome'] for r in records)
    binary = [(r['probability'], 1 if r['outcome'] == 'WON' else 0) for r in records if r['outcome'] in ('WON', 'LOST')]
    scores = score_window(binary, minimum=100)
    return {'settled': sum(counts[k] for k in ('WON', 'LOST', 'VOID', 'PUSH')), 'scored': len(binary),
            'wins': counts['WON'], 'losses': counts['LOST'], 'voids': counts['VOID'], 'pushes': counts['PUSH'],
            'unresolved': counts['UNRESOLVED'], 'pending': counts['PENDING'],
            'hit_rate': round(counts['WON'] / len(binary), 6) if binary else None,
            'brier': scores['brier'], 'log_loss': scores['log_loss'], 'calibration_error': scores['calibration_error'],
            'status': scores['status'], 'roi': None}


def grouped(records, key):
    groups = defaultdict(list)
    for r in records:
        groups[r[key]].append(r)
    return [{'name': name, 'forecasts': len(rows), **metrics(rows)} for name, rows in sorted(groups.items())]


def analytics(db, days=30, at=None):
    at = utc(at or datetime.now(timezone.utc))
    start = at - timedelta(days=days)
    fixtures = {f.id: f for f in db.scalars(select(m.Fixture)).all()}
    competitions = {c.id: c for c in db.scalars(select(m.Competition)).all()}
    sports = {s.id: s.name for s in db.scalars(select(m.Sport)).all()}
    models = {x.id: x for x in db.scalars(select(m.ModelVersion)).all()}
    effective = {p.id: (s, r) for s, p, r in latest_settlement_rows(db)}
    forecasts = db.scalars(select(m.Prediction).where(m.Prediction.predicted_at >= start, m.Prediction.predicted_at <= at)
                           .order_by(m.Prediction.predicted_at, m.Prediction.id)).all()
    records = []
    excluded = 0
    for p in forecasts:
        f = fixtures.get(p.fixture_id)
        # Retrospective and malformed probabilities cannot enter prospective evaluation.
        if not f or utc(p.predicted_at) >= utc(f.kickoff_at) or not 0 < float(p.probability) < 1:
            excluded += 1
            continue
        c = competitions.get(f.competition_id)
        model = models.get(p.model_id)
        settlement, result = effective.get(p.id, (None, None))
        if result and (utc(result.verified_at) > at or utc(result.verified_at) < utc(f.kickoff_at)):
            settlement, result = None, None
        records.append({'id': p.id, 'fixture_id': f.id, 'fixture': f'{f.home_name} vs {f.away_name}',
                        'league': c.name if c else 'Unknown competition', 'sport': sports.get(c.sport_id, 'Unknown sport') if c else 'Unknown sport',
                        'market': p.market_key, 'selection': p.outcome_key, 'model_id': p.model_id,
                        'model': f'{model.name} · {model.version}' if model else p.model_id,
                        'probability': float(p.probability), 'outcome': settlement.outcome if settlement else 'PENDING',
                        'predicted_at': utc(p.predicted_at).isoformat(), 'verified_at': utc(result.verified_at).isoformat() if result else None,
                        'result_version': result.version if result else None})
    stats = metrics(records)
    calibration = []
    for i in range(10):
        members = [r for r in records if r['outcome'] in ('WON', 'LOST') and min(int(r['probability'] * 10), 9) == i]
        if members:
            calibration.append({'bin': f'{i*10}–{(i+1)*10}%', 'count': len(members),
                                'mean_probability': round(sum(r['probability'] for r in members)/len(members), 6),
                                'actual_rate': round(sum(r['outcome'] == 'WON' for r in members)/len(members), 6)})
    daily = defaultdict(list)
    for r in records:
        if r['verified_at'] and r['outcome'] in ('WON', 'LOST'):
            day = datetime.fromisoformat(r['verified_at']).astimezone(ZoneInfo('Africa/Lagos')).date().isoformat()
            daily[day].append(r)
    trend = []
    cumulative = []
    for day, items in sorted(daily.items()):
        cumulative.extend(items)
        trend.append({'date': day, 'daily_count': len(items), **metrics(cumulative)})
    programme_rows = db.execute(select(m.Programme, m.Ticket, m.Qualification.prediction_id)
                               .join(m.Ticket, m.Ticket.programme_id == m.Programme.id)
                               .join(m.TicketLeg, m.TicketLeg.ticket_id == m.Ticket.id)
                               .join(m.Qualification, m.TicketLeg.qualification_id == m.Qualification.id)).all()
    memberships = defaultdict(set)
    ticket_ids = defaultdict(set)
    for programme, ticket, prediction_id in programme_rows:
        memberships[programme.id].add(prediction_id)
        ticket_ids[programme.id].add(ticket.id)
    programmes = []
    for programme in db.scalars(select(m.Programme).order_by(m.Programme.key)).all():
        members = [r for r in records if r['id'] in memberships[programme.id]]
        programmes.append({'name': programme.key, 'forecasts': len(members), 'tickets': len(ticket_ids[programme.id]),
                           **metrics(members), 'unit': 'UNIQUE_FORECASTS_IN_PROGRAMME'})
    model_groups = {g['name']: g for g in grouped(records, 'model_id')}
    snapshots = db.scalars(select(m.ModelGovernanceSnapshot).order_by(m.ModelGovernanceSnapshot.created_at.desc())).all()
    latest_governance = {}
    for snapshot in snapshots:
        latest_governance.setdefault(snapshot.model_id, snapshot)
    comparisons = []
    for model in sorted(models.values(), key=lambda x: (x.name, x.version, x.id)):
        snap = latest_governance.get(model.id)
        comparisons.append({**model_groups.get(model.id, {'forecasts': 0, **metrics([])}), 'id': model.id, 'name': model.name,
                            'version': model.version, 'registry_status': model.status,
                            'monitoring': snap.status if snap else 'NOT_EVALUATED', 'reasons': snap.reasons if snap else [],
                            'evaluated_at': utc(snap.created_at).isoformat() if snap else None})
    updates = db.scalars(select(m.AuditEvent).where(or_(m.AuditEvent.action.like('result.%'), m.AuditEvent.action.like('governance.%'), m.AuditEvent.action.like('model.%')))
                         .order_by(m.AuditEvent.created_at.desc(), m.AuditEvent.id).limit(50)).all()
    workers = []
    for runtime in db.scalars(select(m.AutonomousRuntime).order_by(m.AutonomousRuntime.id)).all():
        online = bool(runtime.lease_until and utc(runtime.lease_until) > at)
        workers.append({'name': runtime.id, 'state': 'OPERATIONAL' if online and not runtime.consecutive_errors else 'DEGRADED' if online else 'OFFLINE',
                        'cycles': runtime.cycles, 'errors': runtime.consecutive_errors, 'last_success_at': utc(runtime.last_success_at).isoformat() if runtime.last_success_at else None})
    return {'mode': 'PAPER', 'observed_at': at.isoformat(), 'period_days': days, 'period_start': start.isoformat(),
            'period_basis': 'FORECAST_ISSUED_AT', 'metrics': stats, 'total_forecasts': len(records), 'excluded_forecasts': excluded,
            'trend': trend, 'calibration': calibration, 'by_sport': grouped(records, 'sport'), 'by_league': grouped(records, 'league'),
            'by_market': grouped(records, 'market'), 'programmes': programmes, 'models': comparisons,
            'profitability': {'status': 'UNAVAILABLE', 'starting_bankroll': None, 'current_bankroll': None, 'net_profit': None,
                              'roi': None, 'max_drawdown': None, 'series': [], 'reason': 'No settlement-linked stake and bankroll ledger is recorded.'},
            'learning': {'scored_forecasts': stats['scored'], 'status': stats['status'], 'model_evaluations': len(snapshots),
                         'automatic_retraining': False, 'automatic_deployment': False,
                         'note': 'Model comparison uses each model’s available forecast cohort; samples are not paired holdout trials.'},
            'workers': workers, 'updates': [{'id': e.id, 'at': utc(e.created_at).isoformat(), 'event': e.action, 'actor': e.actor, 'detail': e.payload} for e in updates],
            'records': records}
