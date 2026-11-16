"""Model registry and governance views without changing lifecycle state."""
from collections import defaultdict
from datetime import datetime, timezone
from sqlalchemy import select, or_, func
from app.db import models as m
from app.modules.prediction.prospective import REQUIRED_APPROVALS
from app.modules.results.performance import analytics, metrics, utc


def workspace(db, days=30, at=None):
    at = utc(at or datetime.now(timezone.utc))
    performance = analytics(db, days, at)
    records = defaultdict(list)
    for row in performance['records']:
        records[row['model_id']].append(row)
    snapshots = db.scalars(select(m.ModelGovernanceSnapshot).order_by(m.ModelGovernanceSnapshot.created_at.desc(), m.ModelGovernanceSnapshot.id)).all()
    histories = defaultdict(list)
    for snap in snapshots:
        histories[snap.model_id].append({'id': snap.id, 'at': utc(snap.created_at).isoformat(), 'status': snap.status,
                                         'reasons': snap.reasons, 'reference': snap.reference, 'recent': snap.recent})
    sports = {s.id: s.name for s in db.scalars(select(m.Sport)).all()}
    registry = []
    training = []
    for model in db.scalars(select(m.ModelVersion).order_by(m.ModelVersion.name, m.ModelVersion.version, m.ModelVersion.id)).all():
        artifact = model.validation if isinstance(model.validation, dict) else {}
        approvals = {key: artifact.get(key) is True for key in REQUIRED_APPROVALS}
        approved_active = model.status == 'ACTIVE' and all(approvals.values())
        history = histories[model.id]
        latest = history[0] if history else None
        bins = []
        for entry in artifact.get('reliability_bins') or []:
            if isinstance(entry, dict) and all(isinstance(entry.get(k), (int, float)) for k in ('predicted', 'observed', 'count')):
                bins.append({k: entry[k] for k in ('predicted', 'observed', 'count')})
        markets = []
        for name, item in (artifact.get('markets') or {}).items():
            if not isinstance(item, dict):
                continue
            markets.append({'name': name, 'approved': item.get('approved') is True, 'reasons': item.get('reasons') or [],
                            'holdout': item.get('holdout') or {}, 'baseline': item.get('baseline') or {},
                            'calibration_error': item.get('calibration_error')})
        promotion = artifact.get('promotion') if isinstance(artifact.get('promotion'), dict) else {}
        model_records = records[model.id]
        daily = defaultdict(list)
        for row in model_records:
            if row['verified_at'] and row['outcome'] in ('WON', 'LOST'):
                daily[row['verified_at'][:10]].append(row)
        cumulative = []
        trend = []
        for day, rows in sorted(daily.items()):
            cumulative.extend(rows)
            trend.append({'date': day, **metrics(cumulative)})
        row = {'id': model.id, 'name': model.name, 'version': model.version, 'sport': sports.get(model.sport_id),
               'type': artifact.get('model_type', 'logistic'), 'registry_status': model.status,
               'approved_active': approved_active, 'approvals': approvals,
               'monitoring': latest['status'] if latest else 'NOT_EVALUATED', 'reasons': latest['reasons'] if latest else [],
               'evaluated_at': latest['at'] if latest else None, 'training_count': artifact.get('training_count'),
               'holdout_count': artifact.get('holdout_count'), 'holdout': artifact.get('holdout_metrics') or {},
               'baseline': artifact.get('baseline_metrics') or {}, 'reliability': bins,
               'calibration_error': artifact.get('calibration_error'), 'training_result_before': artifact.get('training_result_before'),
               'holdout_first_result': artifact.get('holdout_first_result'), 'validated_at': artifact.get('validated_at'),
               'promoted_at': promotion.get('promoted_at'), 'promotion_actor': promotion.get('actor'),
               'markets': markets, 'metrics': metrics(model_records), 'forecast_count': len(model_records), 'trend': trend,
               'history': history[:100]}
        registry.append(row)
        if artifact.get('training_count') is not None:
            training.append({'id': model.id, 'name': model.name, 'version': model.version, 'training_count': artifact.get('training_count'),
                             'holdout_count': artifact.get('holdout_count'), 'status': 'ARTIFACT_RECORDED',
                             'registry_status': model.status, 'validated_at': artifact.get('validated_at')})
    events = db.scalars(select(m.AuditEvent).where(or_(m.AuditEvent.action.like('model.%'), m.AuditEvent.action.like('governance.%')))
                        .order_by(m.AuditEvent.created_at.desc(), m.AuditEvent.id).limit(100)).all()
    training_state = []
    for state in db.scalars(select(m.ProviderSyncState).where(m.ProviderSyncState.id.in_(['autonomy:modelling', 'autonomy:market-model']))).all():
        payload = state.payload if isinstance(state.payload, dict) else {}
        training_state.append({'name': state.id, 'next_check_at': utc(state.next_check_at).isoformat() if state.next_check_at else None,
                               'trained_at': payload.get('trained_at'), 'model_id': payload.get('model_id'),
                               'examples': payload.get('examples'), 'promoted': payload.get('promoted'), 'reasons': payload.get('reasons') or []})
    incidents = db.scalars(select(m.Incident).where(m.Incident.status == 'OPEN', m.Incident.message.like('MODEL%')).order_by(m.Incident.id)).all()
    return {'mode': 'PAPER', 'live_wagers': False, 'observed_at': at.isoformat(), 'period_days': days,
            'summary': {'registered': len(registry), 'training_artifacts': len(training), 'experiments': None,
                        'approved_active': sum(r['approved_active'] for r in registry), 'evaluations': len(snapshots),
                        'monitoring_blocked': sum(r['monitoring'] == 'BLOCKED' for r in registry)},
            'registry': registry, 'training': training, 'training_state': training_state, 'experiment_queue_status': 'NOT_RECORDED',
            'workers': performance['workers'],
            'pipeline': [{'name': 'Data acquisition', 'state': 'SOURCE_LINKED', 'count': db.scalar(select(func.count(m.ResultEvidence.id)))},
                         {'name': 'Feature snapshots', 'state': 'RECORDED', 'count': db.scalar(select(func.count(m.Feature.id)))},
                         {'name': 'Training artifacts', 'state': 'RECORDED', 'count': len(training)},
                         {'name': 'Validation snapshots', 'state': 'RECORDED', 'count': len(snapshots)},
                         {'name': 'Recorded approvals', 'state': 'ACTIVE_APPROVED', 'count': sum(r['approved_active'] for r in registry)},
                         {'name': 'Deployment mode', 'state': 'PAPER', 'count': None}],
            'alerts': [{'id': i.id, 'severity': i.severity, 'message': i.message, 'status': i.status} for i in incidents],
            'activity': [{'id': e.id, 'at': utc(e.created_at).isoformat(), 'actor': e.actor, 'event': e.action, 'model_id': e.correlation_id, 'detail': e.payload} for e in events],
            'boundaries': {'dashboard_access': 'READ_ONLY', 'approval_policy': 'EXISTING_SERVER_SIDE_VALIDATION_GATES',
                           'automatic_lifecycle': 'EXISTING_WORKERS_ONLY', 'experiment_queue': 'NOT_RECORDED',
                           'prediction_drift_psi': 'NOT_RECORDED', 'data_freshness_sla': 'NOT_MEASURED', 'live_wagers': False}}
