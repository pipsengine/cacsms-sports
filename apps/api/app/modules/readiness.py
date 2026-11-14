"""Runtime readiness; a live API is not equivalent to a working sports intelligence system."""
from datetime import datetime, timezone
from sqlalchemy import select, func, text
from sqlalchemy.exc import SQLAlchemyError
from app.db.base import SessionLocal
from app.db import models as m

def assess_readiness():
    checks = {"api": "READY", "postgresql": "UNAVAILABLE", "authorized_sources": "UNAVAILABLE", "approved_models": "UNAVAILABLE", "qualified_opportunities": "UNAVAILABLE", "live_betting": "DISABLED"}
    details = {"mode": "PAPER", "evaluated_at": datetime.now(timezone.utc).isoformat()}
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            checks["postgresql"] = "READY"
            source_count = db.scalar(select(func.count()).select_from(m.Source).where(m.Source.enabled.is_(True), m.Source.permission == "AUTHORIZED")) or 0
            details["authorized_source_count"] = source_count
            if source_count: checks["authorized_sources"] = "READY"
            model_count = db.scalar(select(func.count()).select_from(m.ModelVersion)) or 0
            details["registered_model_count"] = model_count
            # Merely registering a model is not independent approval.
            qualified_count = db.scalar(select(func.count()).select_from(m.Qualification).where(m.Qualification.decision == "QUALIFIED")) or 0
            details["qualified_opportunity_count"] = qualified_count
            if qualified_count: checks["qualified_opportunities"] = "RECORDS_PRESENT_NOT_REVALIDATED"
    except SQLAlchemyError as exc:
        details["database_error_type"] = type(exc).__name__
    return {"ready_for_autonomous_predictions": False, "checks": checks, "details": details}
