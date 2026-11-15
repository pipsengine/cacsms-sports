from fastapi import APIRouter,HTTPException,Query
from sqlalchemy.exc import SQLAlchemyError
from app.db.base import SessionLocal
from app.modules.autonomy.overview import snapshot
from app.modules.autonomy.service import runtime_status
router=APIRouter(prefix='/api/v1/sports',tags=['Autonomous dashboard'])

@router.get('/dashboard/autonomous')
def autonomous_dashboard(hours:int=Query(72,ge=1,le=168)):
 try:
  with SessionLocal() as db:return snapshot(db,hours)
 except SQLAlchemyError as exc:raise HTTPException(503,'Dashboard database unavailable or migrations missing') from exc

@router.get('/autonomy/status')
def status():
 try:
  with SessionLocal() as db:return runtime_status(db)
 except SQLAlchemyError as exc:raise HTTPException(503,'Autonomous runtime database unavailable or migrations missing') from exc
