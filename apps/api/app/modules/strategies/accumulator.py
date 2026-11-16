"""Accumulator Engine: the shared programme engine bound to the 'accumulator' programme (see programme_engine)."""
from app.modules.strategies import programme_engine as pe
from app.modules.strategies.programme_engine import REQUIRED_GATES,OPTIONAL_GATES,APPROVALS,FRESHNESS,gates_pass,eligible,settle,validation

KEY='accumulator'
BUCKET_MINUTES=pe.SETTINGS[KEY]['bucket_minutes']


def policy():return pe.policy(KEY)
def bucket(at):return pe.bucket(KEY,at)
def run_once(db,at=None,trigger='autonomous'):return pe.run_once(db,KEY,at,trigger)
def cycle(factory,at=None):return pe.cycle(factory,KEY,at)
def runs(db,limit=50,offset=0):return pe.runs(db,KEY,limit,offset)
def overview(db,at=None):return pe.overview(db,KEY,at)
def analytics(db,at,count=30):return pe.analytics(db,KEY,at,count)
