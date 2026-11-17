"""Review proposals only: reconciliation never changes approval or activation."""
from sqlalchemy import select
from app.db import models as m
from app.modules.prediction.prospective import REQUIRED_APPROVALS


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
