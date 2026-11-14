"""Observe persisted odds changes and freshness; never synthesize provider evidence."""
from datetime import datetime,timezone,timedelta
from decimal import Decimal
from sqlalchemy import select
from app.db import models as m

def inspect_market(db,fixture_id,*,at=None):
    at=at or datetime.now(timezone.utc)
    prices=db.scalars(select(m.Odds).where(m.Odds.fixture_id==fixture_id).order_by(m.Odds.observed_at.desc())).all()
    grouped={}
    for price in prices:
        grouped.setdefault((price.bookmaker,price.market_key,price.outcome_key),[]).append(price)
    alerts=[];snapshots=[]
    for key,rows in grouped.items():
        current=rows[0]
        observed=current.observed_at
        if observed and observed.tzinfo is None:observed=observed.replace(tzinfo=timezone.utc)
        fresh=bool(observed and timedelta(0)<=at-observed<=timedelta(minutes=15))
        previous=rows[1] if len(rows)>1 else None
        delta=str(Decimal(str(current.decimal_odds))-Decimal(str(previous.decimal_odds))) if previous else None
        snapshots.append({'bookmaker':key[0],'market':key[1],'outcome':key[2],'odds_id':current.id,'fresh':fresh,'delta':delta})
        if not fresh:alerts.append({'odds_id':current.id,'reason':'STALE_PRICE'})
        elif previous and delta!='0':alerts.append({'odds_id':current.id,'reason':'PRICE_CHANGED','delta':delta})
    return {'fixture_id':fixture_id,'snapshots':snapshots,'alerts':alerts,'monitoring_verified':False,'reason':'Internal odds inspection is not independent external monitoring evidence'}
