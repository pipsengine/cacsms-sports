"""Offline parsing of SportyBet-shaped snapshots; no collection or authorization."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation


class SnapshotError(ValueError):
    pass


def _text(value):
    return value.strip() if isinstance(value, str) else ''


def _id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return ''
    return str(value).strip()


def _active(value, expected):
    return type(value) in (int, str) and value in (expected, str(expected))


def parse_snapshot(payload, *, sport, observed_at):
    """Return unverified fixture candidates and 1X2 prices from a supplied snapshot.

    The caller must supply the actual capture time and reconcile fixture identities.
    No source is contacted and no observations or authorizations are created.
    """
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None:
        raise SnapshotError('CAPTURE_TIME_TIMEZONE_REQUIRED')
    if not isinstance(sport, str) or not sport.strip():
        raise SnapshotError('SPORT_REQUIRED')
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), dict):
        raise SnapshotError('INVALID_SNAPSHOT')
    tournaments = payload['data'].get('tournaments')
    if not isinstance(tournaments, list) or len(tournaments) > 10000:
        raise SnapshotError('INVALID_TOURNAMENTS')
    captured = observed_at.astimezone(timezone.utc).isoformat()
    fixtures, rejected = [], []
    seen, duplicates = set(), set()
    for ti, tournament in enumerate(tournaments):
        if not isinstance(tournament, dict):
            rejected.append({'location': f'tournaments[{ti}]', 'reason': 'INVALID_TOURNAMENT'})
            continue
        league_id = _id(tournament.get('id') or tournament.get('tournamentId'))
        league_name = _text(tournament.get('name'))
        events = tournament.get('events')
        if not league_id or not league_name or not isinstance(events, list) or len(events) > 10000:
            rejected.append({'location': f'tournaments[{ti}]', 'reason': 'INVALID_COMPETITION'})
            continue
        for ei, event in enumerate(events):
            location = f'tournaments[{ti}].events[{ei}]'
            if not isinstance(event, dict):
                rejected.append({'location': location, 'reason': 'INVALID_EVENT'})
                continue
            event_id = _id(event.get('eventId'))
            home, away = _text(event.get('homeTeamName')), _text(event.get('awayTeamName'))
            if not event_id or not home or not away or home.casefold() == away.casefold():
                rejected.append({'location': location, 'reason': 'INVALID_FIXTURE_IDENTITY'})
                continue
            if event_id in seen:
                rejected.append({'location': location, 'reason': 'DUPLICATE_EVENT_ID'})
                duplicates.add(event_id)
                continue
            raw_time = event.get('estimateStartTime')
            try:
                if isinstance(raw_time, bool) or not isinstance(raw_time, (int, str)):
                    raise ValueError('invalid epoch')
                epoch = int(raw_time)
                if epoch <= 0:
                    raise ValueError('invalid epoch')
                kickoff = datetime.fromtimestamp(epoch / 1000, tz=timezone.utc)
            except (ValueError, OverflowError, OSError):
                rejected.append({'location': location, 'reason': 'INVALID_KICKOFF'})
                continue
            markets = event.get('markets')
            if not isinstance(markets, list) or len(markets) > 10000:
                rejected.append({'location': location, 'reason': 'INVALID_MARKETS'})
                markets = []
            seen.add(event_id)
            prices = []
            if sport.strip().casefold() == 'football':
                mapped, conflicted = set(), set()
                for mi, market in enumerate(markets):
                    where = f'{location}.markets[{mi}]'
                    if not isinstance(market, dict):
                        rejected.append({'location': where, 'reason': 'INVALID_MARKET'})
                        continue
                    if not _active(market.get('status'), 0):
                        continue
                    label = _text(market.get('desc') or market.get('name')).casefold()
                    if label != '1x2' or market.get('specifier'):
                        continue
                    outcomes = market.get('outcomes')
                    if not isinstance(outcomes, list) or len(outcomes) > 100:
                        rejected.append({'location': where, 'reason': 'INVALID_OUTCOMES'})
                        continue
                    for oi, outcome in enumerate(outcomes):
                        position = f'{where}.outcomes[{oi}]'
                        if not isinstance(outcome, dict):
                            rejected.append({'location': position, 'reason': 'INVALID_OUTCOME'})
                            continue
                        if not _active(outcome.get('isActive'), 1):
                            continue
                        side = {'1': 'HOME', 'home': 'HOME', 'x': 'DRAW', 'draw': 'DRAW',
                                '2': 'AWAY', 'away': 'AWAY'}.get(_text(outcome.get('desc')).casefold())
                        try:
                            price = Decimal(str(outcome.get('odds')))
                            if not price.is_finite() or not 1 < price <= 1000 or price.as_tuple().exponent < -5:
                                raise ValueError('invalid odds')
                        except (InvalidOperation, ValueError):
                            rejected.append({'location': position, 'reason': 'INVALID_ODDS'})
                            continue
                        if side is None:
                            rejected.append({'location': position, 'reason': 'AMBIGUOUS_OUTCOME'})
                            continue
                        if side in mapped or side in conflicted:
                            prices = [row for row in prices if row['outcome_key'] != side]
                            conflicted.add(side)
                            rejected.append({'location': position, 'reason': 'DUPLICATE_OUTCOME'})
                            continue
                        mapped.add(side)
                        prices.append({'bookmaker': 'SportyBet', 'market_key': '1X2',
                                       'outcome_key': side, 'decimal_odds': str(price), 'observed_at': captured})
            fixtures.append({'provider_event_id': event_id, 'competition_id': league_id,
                             'competition': league_name, 'country': _text(tournament.get('categoryName')) or None,
                             'sport': sport.strip(), 'home': home, 'away': away, 'kickoff_at': kickoff.isoformat(),
                             'status': 'UNVERIFIED', 'prices': prices})
    return {'fixtures': [row for row in fixtures if row['provider_event_id'] not in duplicates], 'rejected': rejected}
