"""Read catalogue and administrator-only season/standings intake."""
import hashlib
import json
from datetime import date, datetime, timezone
from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field, ConfigDict, model_validator
from sqlalchemy import select
from app.db import models as m
from app.db.base import SessionLocal
from app.modules.research import catalog
from app.modules.research.league import utc as database_utc
from app.modules.results.routes import admin_only
from app.modules.acquisition.service import validate_url, utc

router = APIRouter(prefix='/api/v1/sports', tags=['Research catalogue'])


def read(action):
    try:
        with SessionLocal() as db:
            return action(db)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, PermissionError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.get('/research/catalog/sports')
def sports():
    return read(lambda db: [dict(id=s.id, name=s.name) for s in db.scalars(select(m.Sport).order_by(m.Sport.name))])


@router.get('/research/catalog/countries')
def countries(sport: str):
    return read(lambda db: [dict(name=name) for name in db.scalars(select(m.Competition.country).join(m.Sport)
        .where(m.Sport.name == sport, m.Competition.country.is_not(None)).distinct().order_by(m.Competition.country))])


@router.get('/research/catalog/leagues')
def leagues(sport: str, country: str | None = None):
    def load(db):
        query = select(m.Competition).join(m.Sport).where(m.Sport.name == sport)
        if country:
            query = query.where(m.Competition.country == country)
        return [dict(id=c.id, name=c.name, country=c.country) for c in db.scalars(query.order_by(m.Competition.name))]
    return read(load)


@router.get('/research/catalog/seasons')
def seasons(league_id: str):
    def load(db):
        catalog.competition_season(db, league_id)
        return [dict(id=s.id, label=s.label, start_date=s.start_date, end_date=s.end_date, is_current=s.is_current)
                for s in db.scalars(select(m.CompetitionSeason).where(m.CompetitionSeason.competition_id == league_id)
                                   .order_by(m.CompetitionSeason.start_date.desc()))]
    return read(load)


@router.get('/research/catalog/fixtures')
def fixtures(league_id: str, season_id: str | None = None, limit: int = Query(100, ge=1, le=500)):
    return read(lambda db: catalog.fixtures(db, league_id, season_id, limit))


@router.get('/research/catalog/standings')
def standings(league_id: str, season_id: str | None = None, as_of: datetime | None = None, scope: str = 'overall'):
    return read(lambda db: catalog.standings(db, league_id, season_id, as_of, scope))


@router.get('/research/catalog/dossiers/{fixture_id}')
def dossier(fixture_id: str, as_of: datetime | None = None):
    return read(lambda db: catalog.dossier(db, fixture_id, as_of))


class SeasonIn(BaseModel):
    competition_id: str
    label: str = Field(min_length=1, max_length=100)
    start_date: date
    end_date: date
    is_current: bool = False
    country: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode='after')
    def ordered(self):
        if self.end_date < self.start_date:
            raise ValueError('Season end must follow start')
        return self


@router.post('/admin/research/seasons', status_code=201)
def save_season(item: SeasonIn, x_admin_token: str | None = Header(default=None)):
    admin_only(x_admin_token)
    with SessionLocal.begin() as db:
        competition = db.get(m.Competition, item.competition_id)
        if competition is None:
            raise HTTPException(404, 'Competition not found')
        if item.country:
            competition.country = item.country
        season = db.scalar(select(m.CompetitionSeason).where(m.CompetitionSeason.competition_id == item.competition_id,
                                                            m.CompetitionSeason.label == item.label))
        if season is None:
            season = m.CompetitionSeason(competition_id=item.competition_id, label=item.label)
            db.add(season)
        if item.is_current:
            for previous in db.scalars(select(m.CompetitionSeason).where(m.CompetitionSeason.competition_id == item.competition_id)):
                previous.is_current = False
        if season.id:
            assigned = db.scalars(select(m.Fixture).where(m.Fixture.season_id == season.id)).all()
            if any(not item.start_date <= database_utc(f.kickoff_at).date() <= item.end_date for f in assigned):
                raise HTTPException(422, 'Season dates would exclude assigned fixtures')
        season.start_date, season.end_date, season.is_current = item.start_date, item.end_date, item.is_current
        db.flush()
        db.add(m.AuditEvent(actor='admin', action='research.season_saved', correlation_id=season.id,
                           payload={'competition_id':item.competition_id,'label':item.label}))
        return dict(id=season.id, label=season.label, mode='PAPER')


class SeasonAssignment(BaseModel):
    fixture_ids: list[str] = Field(min_length=1, max_length=500)


@router.post('/admin/research/seasons/{season_id}/fixtures')
def assign_season(season_id: str, item: SeasonAssignment, x_admin_token: str | None = Header(default=None)):
    admin_only(x_admin_token)
    with SessionLocal.begin() as db:
        season = db.get(m.CompetitionSeason, season_id)
        if season is None:
            raise HTTPException(404, 'Season not found')
        for fixture_id in set(item.fixture_ids):
            fixture = db.get(m.Fixture, fixture_id)
            if fixture is None or fixture.competition_id != season.competition_id:
                raise HTTPException(422, 'Every fixture must belong to this competition')
            if not season.start_date <= database_utc(fixture.kickoff_at).date() <= season.end_date:
                raise HTTPException(422, 'Fixture kickoff is outside season dates')
            fixture.season_id = season.id
        db.add(m.AuditEvent(actor='admin', action='research.fixtures_season_assigned', correlation_id=season.id,
                           payload={'fixture_ids':sorted(set(item.fixture_ids))}))
        return dict(season_id=season.id, assigned=len(set(item.fixture_ids)))


class StandingEntry(BaseModel):
    model_config = ConfigDict(strict=True, extra='forbid', str_strip_whitespace=True)
    club: str = Field(min_length=1, max_length=200)
    rank: int = Field(ge=1)
    played: int = Field(ge=0)
    wins: int = Field(ge=0)
    draws: int = Field(ge=0)
    losses: int = Field(ge=0)
    goals_for: int | None = Field(default=None, ge=0)
    goals_against: int | None = Field(default=None, ge=0)
    goal_difference: int | None = None
    points: int
    form: str | None = Field(default=None, pattern='^[WDL]{0,20}$')

    @model_validator(mode='after')
    def consistent(self):
        if self.played != self.wins + self.draws + self.losses:
            raise ValueError('Played must equal wins plus draws plus losses')
        values = (self.goals_for, self.goals_against, self.goal_difference)
        if any(v is not None for v in values) and (any(v is None for v in values) or self.goal_difference != self.goals_for - self.goals_against):
            raise ValueError('Inconsistent goal difference totals')
        return self


class SnapshotIn(BaseModel):
    competition_id: str
    season_id: str
    source_id: str
    source_url: str
    source_reference: str = Field(min_length=1, max_length=1000)
    captured_at: datetime
    verified_at: datetime
    official: bool = False
    scope: str = Field(default='overall', pattern='^(overall|home|away)$')
    entries: list[StandingEntry] = Field(min_length=1, max_length=500)

    @model_validator(mode='after')
    def consistent(self):
        if len({e.club for e in self.entries}) != len(self.entries) or len({e.rank for e in self.entries}) != len(self.entries):
            raise ValueError('Duplicate clubs or ranks')
        captured, verified = utc(self.captured_at), utc(self.verified_at)
        if captured > verified or verified > datetime.now(timezone.utc):
            raise ValueError('Capture must precede verification; neither may be future-dated')
        validate_url(self.source_url)
        return self


@router.post('/admin/research/standings', status_code=201)
def ingest_standings(item: SnapshotIn, x_admin_token: str | None = Header(default=None)):
    admin_only(x_admin_token)
    with SessionLocal.begin() as db:
        try:
            catalog.competition_season(db, item.competition_id, item.season_id)
        except (ValueError, LookupError) as exc:
            raise HTTPException(422, str(exc)) from exc
        source = db.get(m.Source, item.source_id)
        if source is None or not source.enabled or source.permission != 'AUTHORIZED':
            raise HTTPException(422, 'Enabled authorized source required')
        payload = item.model_dump(mode='json')
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',',':')).encode()).hexdigest()
        previous = db.scalar(select(m.StandingsSnapshot).where(m.StandingsSnapshot.source_id == source.id,
                                                             m.StandingsSnapshot.content_hash == digest))
        if previous:
            return dict(id=previous.id, replayed=True, mode='PAPER')
        snapshot = m.StandingsSnapshot(review_status='VERIFIED', reviewed_by='admin', **item.model_dump(exclude={'entries'}), entries=[e.model_dump() for e in item.entries], content_hash=digest)
        db.add(snapshot)
        db.flush()
        db.add(m.AuditEvent(actor='admin', action='research.standings_verified', correlation_id=snapshot.id,
                           payload={'source_id':source.id,'content_hash':digest,'scope':item.scope}))
        return dict(id=snapshot.id, replayed=False, mode='PAPER')



@router.get('/research/catalog/coverage')
def standings_coverage(league_id: str, season_id: str, as_of: datetime | None = None):
    return read(lambda db: catalog.standings_coverage(db, league_id, season_id, as_of))


@router.get('/research/catalog/standings/history')
def standings_history(league_id: str, season_id: str, scope: str = 'overall', before: datetime | None = None, limit: int = Query(20, ge=1, le=100)):
    return read(lambda db: catalog.standings_history(db, league_id, season_id, scope, before, limit))
