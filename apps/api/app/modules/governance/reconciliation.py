"""Review legacy labels without changing registry status, approval or deployment."""
from sqlalchemy import select
from app.db import models as m
from app.modules.prediction.prospective import REQUIRED_APPROVALS


def reconcile_labels(db, model_id, *, actor, review_reference):
    """Correct reviewed legacy labels only; never grant approval or change status."""
    if not actor.strip() or not review_reference.strip(): raise ValueError('Named reviewer and review evidence required')
    from app.modules.governance.promotion import assess_challenger
    model = db.scalar(select(m.ModelVersion).where(m.ModelVersion.id == model_id).with_for_update())
    if model is None: raise LookupError('Unknown model')
    artifact = model.validation or {}
    passed, reasons, evidence = assess_challenger(artifact)
    if model.status != 'ACTIVE' or not all(artifact.get(key) is True for key in REQUIRED_APPROVALS) or not passed:
        raise ValueError('Existing approval and current validation must already pass: ' + ','.join(reasons))
    promotion = artifact.get('promotion') or {}
    recorded = (promotion.get('evidence') or {}).get('holdout')
    audits = db.scalars(select(m.AuditEvent).where(m.AuditEvent.correlation_id == model_id, m.AuditEvent.action == 'model.promoted')).all()
    if recorded != evidence.get('holdout') or not any((row.payload.get('evidence') or {}).get('holdout') == recorded for row in audits):
        raise ValueError('Matching original promotion audit evidence is required')
    before = {key: artifact.get(key) for key in ('status', 'activation_allowed', 'note')}
    if before['status'] == 'ACTIVE' and before['activation_allowed'] is True:
        return {'model_id': model_id, 'changed': False, 'automatic_activation': False}
    after = {'status': 'ACTIVE', 'activation_allowed': True,
             'note': 'Legacy labels reconciled against the recorded, independently validated promotion; registry and approval unchanged'}
    model.validation = {**artifact, **after}
    db.add(m.AuditEvent(actor=actor, action='model.legacy_labels_reconciled', correlation_id=model_id,
                       payload={'review_reference': review_reference, 'original_labels': before, 'corrected_labels': after,
                                'validation_evidence': evidence, 'registry_status_changed': False, 'approvals_changed': False}))
    return {'model_id': model_id, 'changed': True, 'original_labels': before, 'corrected_labels': after,
            'registry_status_changed': False, 'approvals_changed': False, 'automatic_activation': False}


def review(db):
    proposals = []
    for model in db.scalars(select(m.ModelVersion).order_by(m.ModelVersion.id)):
        artifact = model.validation or {}
        approved = all(artifact.get(key) is True for key in REQUIRED_APPROVALS)
        inconsistencies = []
        if model.status == 'ACTIVE' and not approved: inconsistencies.append('ACTIVE_WITHOUT_REQUIRED_APPROVALS')
        if model.status == 'ACTIVE' and artifact.get('status') == 'CHALLENGER': inconsistencies.append('LEGACY_ARTIFACT_STATUS')
        if model.status == 'ACTIVE' and artifact.get('activation_allowed') is False: inconsistencies.append('LEGACY_ACTIVATION_LABEL')
        if inconsistencies:
            proposals.append({'model_id': model.id, 'version': model.version, 'registry_status': model.status,
                'required_approvals': {key: artifact.get(key) is True for key in REQUIRED_APPROVALS},
                'deployment_eligible': model.status == 'ACTIVE' and approved,
                'actual_deployment_status': 'UNVERIFIED', 'inconsistencies': inconsistencies,
                'required_action': 'Review original promotion evidence; append an audit event containing original labels before any approved cosmetic correction. Missing approvals require the existing promotion gate.',
                'automatic_activation': False})
    return {'mode': 'PAPER', 'review_required': proposals, 'mutations_performed': 0,
            'policy': 'Never infer approval from registry status; preserve original audit evidence.'}
