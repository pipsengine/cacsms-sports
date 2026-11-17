"""Persisted evaluation history. Missing measurements stay unavailable."""
from sqlalchemy import select, func
from app.db import models as m
from app.modules.prediction.prospective import REQUIRED_APPROVALS


def evaluation_history(db, model_id, limit=50, offset=0):
    model = db.get(m.ModelVersion, model_id)
    query = select(m.ModelGovernanceSnapshot).where(m.ModelGovernanceSnapshot.model_id == model_id)
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    snapshots = db.scalars(query.order_by(m.ModelGovernanceSnapshot.created_at.desc(), m.ModelGovernanceSnapshot.id).offset(offset).limit(limit))
    artifact = model.validation or {}
    approvals = {key: artifact.get(key) is True for key in REQUIRED_APPROVALS}
    rows = []
    for row in snapshots:
        recent = row.recent or {}
        rows.append({'id': row.id, 'model_id': model_id, 'model_version': model.version,
                     'evaluated_at': row.created_at, 'dataset': recent.get('dataset'),
                     'evaluation_window': recent.get('evaluation_window'),
                     'sample_size': recent.get('sample_size', recent.get('count', recent.get('n'))),
                     'brier_score': recent.get('brier'), 'log_loss': recent.get('log_loss'),
                     'calibration_error': recent.get('calibration_error', recent.get('ece')), 'coverage': recent.get('coverage'),
                     'governance_decision': row.status, 'blocking_reasons': row.reasons,
                     'approval_status': recent.get('approval_status'),
                     'evidence_references': recent.get('evidence_ids'),
                     'reference': row.reference, 'recent': row.recent})
    return {'model_id': model_id, 'model_version': model.version, 'total': total,
            'limit': limit, 'offset': offset, 'evaluations': rows,
            'explanation': 'Persisted prospective evaluations; unavailable fields are null.' if total else 'No persisted evaluation exists for this model.',
            'registry_status': model.status, 'current_governance_approvals': approvals,
            'deployment_eligible': model.status == 'ACTIVE' and all(approvals.values()),
            'actual_deployment_status': 'UNVERIFIED', 'automatic_activation': False, 'mode': 'PAPER'}
