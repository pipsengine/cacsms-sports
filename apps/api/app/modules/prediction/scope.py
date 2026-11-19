"""Which competitions a model was validated on. A model may only forecast fixtures inside that scope.

New models record `validation.competition_ids`. Models created before this field existed were trained exclusively on
the autonomous Bundesliga history (`autonomy.modelling`), so they are scoped to that competition, never to the sport.
"""
from sqlalchemy import select
from app.db import models as m


def legacy_competition_id(db):
    from app.modules.autonomy.open_intelligence import COMPETITION
    return db.scalar(select(m.Competition.id).where(m.Competition.name == COMPETITION, m.Competition.country == 'Germany'))


def competitions_for(db, model):
    validation = model.validation if model is not None and isinstance(model.validation, dict) else {}
    ids = validation.get('competition_ids')
    if isinstance(ids, list) and ids:
        return {str(i) for i in ids}
    legacy = legacy_competition_id(db)
    return {legacy} if legacy else set()


def in_scope(db, model, competition_id):
    return competition_id in competitions_for(db, model)
