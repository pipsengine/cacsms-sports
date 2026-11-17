"""Versioned, read-only odds intelligence; mutation remains in authorized ingestion."""
from typing import Literal
from datetime import datetime
from fastapi import APIRouter, Query, HTTPException, Header
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.db.base import SessionLocal
from app.db import models as m
from app.modules.markets.odds_intelligence import assess

router = APIRouter(prefix='/api/v1/sports/odds-intelligence', tags=['Odds Intelligence'])


class OddsAssessmentResponse(BaseModel):
    odds_id: str
    fixture_id: str
    bookmaker: str
    market_key: str
    outcome_key: str
    decimal_odds: float | None
    classification: Literal['HISTORICAL', 'RESEARCH_SNAPSHOT', 'FRESH_MARKET']
    eligible: bool
    rejection_reasons: list[str]
    observed_at: datetime
    age_seconds: float
    freshness_limit_seconds: Literal[900]
    source_id: str | None
    provider: str | None
    observation_id: str | None
    source_url: str | None
    mode: Literal['PAPER']


class ObservationPageResponse(BaseModel):
    observations: list[OddsAssessmentResponse]
    limit: int
    offset: int
    scanned: int
    next_offset: int | None
    freshness_limit_seconds: Literal[900]
    mode: Literal['PAPER']


class SourceProfileInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_type: Literal['CSV', 'API', 'LICENSED_FEED', 'MANUAL_REVIEWED']
    sports: list[str] = Field(default_factory=list, max_length=100)
    leagues: list[str] = Field(default_factory=list, max_length=1000)
    markets: list[str] = Field(default_factory=list, max_length=1000)
    classifications: list[Literal['HISTORICAL', 'RESEARCH_SNAPSHOT', 'FRESH_MARKET']] = Field(default_factory=list, max_length=3)
    collection_method: Literal['PUBLISHED_CSV', 'DOCUMENTED_API', 'LICENSED_API', 'REVIEWED_IMPORT']
    expected_update_seconds: int | None = Field(None, ge=1, le=31536000)
    priority: int = Field(100, ge=0, le=1000)
    fallback_source_ids: list[str] = Field(default_factory=list, max_length=20)
    policy_reference: str | None = Field(None, max_length=2000)
    limitations: list[str] = Field(default_factory=list, max_length=100)


@router.put('/sources/{source_id}/profile')
def configure_source(source_id: str, item: SourceProfileInput, x_admin_token: str | None = Header(None)):
    from app.modules.pipeline.routes import admin_guard
    admin_guard(x_admin_token)
    with SessionLocal.begin() as db:
        if db.get(m.Source, source_id) is None: raise HTTPException(404, 'Unknown source')
        if source_id in item.fallback_source_ids: raise HTTPException(422, 'A source cannot fall back to itself')
        for fallback in item.fallback_source_ids:
            source = db.get(m.Source, fallback)
            if source is None or source.permission != 'AUTHORIZED' or not source.enabled:
                raise HTTPException(422, 'Fallback sources must be enabled and authorized')
        profile = db.get(m.OddsSourceProfile, source_id)
        before = {column.name: getattr(profile, column.name) for column in profile.__table__.columns} if profile else None
        if profile is None:
            profile = m.OddsSourceProfile(source_id=source_id)
            db.add(profile)
        values = item.model_dump()
        for key, value in values.items(): setattr(profile, key, value)
        db.add(m.AuditEvent(actor='admin', action='odds.source_profile_configured', correlation_id=source_id,
                           payload={'before': before, 'after': values, 'authorization_changed': False}))
        return {'source_id': source_id, **values, 'authorization_changed': False, 'mode': 'PAPER'}


@router.get('/observations', response_model=ObservationPageResponse)
def observations(fixture_id: str | None = None,
                 classification: Literal['HISTORICAL', 'RESEARCH_SNAPSHOT', 'FRESH_MARKET'] | None = None,
                 limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    """Pagination is over source rows; classification filters that page explicitly.

    next_offset advances over scanned rows, avoiding unbounded archive scans.
    """
    try:
        with SessionLocal() as db:
            query = select(m.Odds).order_by(m.Odds.observed_at.desc(), m.Odds.id)
            if fixture_id: query = query.where(m.Odds.fixture_id == fixture_id)
            quotes = db.scalars(query.offset(offset).limit(limit + 1)).all()
            rows = [assess(db, quote) for quote in quotes[:limit]]
            return {'observations': [row for row in rows if not classification or row['classification'] == classification],
                    'limit': limit, 'offset': offset, 'scanned': len(rows),
                    'next_offset': offset + limit if len(quotes) > limit else None,
                    'freshness_limit_seconds': 900, 'mode': 'PAPER'}
    except SQLAlchemyError as exc:
        raise HTTPException(503, 'Odds database unavailable') from exc


@router.get('/eligibility/{odds_id}', response_model=OddsAssessmentResponse)
def eligibility(odds_id: str):
    with SessionLocal() as db:
        quote = db.get(m.Odds, odds_id)
        if quote is None: raise HTTPException(404, 'Unknown odds snapshot')
        return assess(db, quote)


@router.get('/sources')
def sources():
    from app.modules.acquisition.source_policy import registry
    with SessionLocal() as db:
        rows = registry(db)
        for row in rows:
            profile = db.get(m.OddsSourceProfile, row['id'])
            row['capabilities'] = {column.name: getattr(profile, column.name) for column in profile.__table__.columns} if profile else None
            row['licensing_status'] = row['permission']
            row['reliability'] = None  # no invented score from observation counts
        return {'sources': rows, 'mode': 'PAPER',
                'notice': 'Results coverage does not imply bookmaker odds coverage.'}


@router.get('/source-readiness')
def source_readiness():
    from app.modules.acquisition.source_policy import registry
    with SessionLocal() as db:
        rows = registry(db)
        for row in rows:
            authorized = row['permission'] == 'AUTHORIZED' and row['status'] == 'ACTIVE'
            row.update(network_reachable='UNVERIFIED', browser_navigation='UNVERIFIED',
                       collection_authorized=authorized, extraction_enabled=authorized,
                       last_authorized_acquisition=row['last_sync'] if authorized else None,
                       data_availability='STORED_OBSERVATIONS' if row['observations'] else 'NO_OBSERVATIONS',
                       required_next_action='Monitor authorized synchronization' if authorized else 'Verify written authorization before collection')
        return {'sources': rows, 'mode': 'PAPER', 'network_success_grants_authorization': False}


@router.get('/quality-assessments')
def quality_assessments(failures_only: bool = False, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    with SessionLocal() as db:
        query = select(m.OddsQualityAssessment).order_by(m.OddsQualityAssessment.assessed_at.desc(), m.OddsQualityAssessment.id)
        if failures_only: query = query.where(m.OddsQualityAssessment.eligible.is_(False))
        return {'assessments': [{column.name: getattr(row, column.name) for column in row.__table__.columns}
                for row in db.scalars(query.offset(offset).limit(limit))], 'limit': limit, 'offset': offset, 'mode': 'PAPER'}
