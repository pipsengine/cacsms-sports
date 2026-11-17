"""Odds provider boundary; result-only providers explicitly declare no odds feed.

Adapters persist through the existing canonical acquisition path. Adding a
licensed provider needs an implementation plus registry entry, not engine edits.
"""
from dataclasses import dataclass
from typing import Protocol


class OddsProvider(Protocol):
    source_id: str
    def acquire(self, factory, *, at): ...


@dataclass(frozen=True)
class FootballDataOdds:
    source_id: str

    def acquire(self, factory, *, at):
        from app.modules.autonomy.open_intelligence import collect_odds
        from app.db import models as m
        from app.modules.acquisition.source_policy import assert_permitted
        from app.modules.autonomy.open_intelligence import FD_FIXTURES
        assert_permitted(FD_FIXTURES)
        with factory() as db:
            source = db.get(m.Source, self.source_id)
            if source is None or source.permission != 'AUTHORIZED' or not source.enabled:
                return {'status': 'SOURCE_NOT_AUTHORIZED', 'fixtures': 0, 'quotes': 0}
        return collect_odds(factory, at=at)


def registry():
    from app.modules.autonomy.open_intelligence import FD_SOURCE_ID
    return {'football-data': FootballDataOdds(FD_SOURCE_ID)}


def acquire(factory, *, at, provider=None):
    from app.db import models as m
    adapters = registry()
    if provider is not None and provider not in adapters:
        return {'status': 'NO_AUTHORIZED_ODDS_ADAPTER', 'fixtures': 0, 'quotes': 0,
                'reason': 'No odds coverage is inferred from fixture/results coverage.'}
    with factory() as db:
        profiles = {key: db.get(m.OddsSourceProfile, adapter.source_id) for key, adapter in adapters.items()}
        priorities = {key: profile.priority if profile else 100 for key, profile in profiles.items()}
        fallbacks = {key: list(profile.fallback_source_ids) if profile else [] for key, profile in profiles.items()}
    queue = [provider] if provider is not None else sorted(adapters, key=lambda key: (priorities[key], key))
    visited = set(); attempts = []; result = None
    while queue:
        key = queue.pop(0)
        if key in visited: continue
        visited.add(key)
        try:
            result = adapters[key].acquire(factory, at=at)
        except Exception as exc:
            # The scheduler owns bounded retries; try only configured adapters here.
            result = {'status': 'PROVIDER_UNAVAILABLE', 'fixtures': 0, 'quotes': 0,
                      'errors': [{'provider': key, 'code': type(exc).__name__, 'detail': str(exc)[:160]}]}
        attempts.append({'provider': key, 'status': result.get('status'), 'quotes': result.get('quotes', 0)})
        if result.get('quotes', 0): break
        queue.extend(name for source_id in fallbacks[key] for name, adapter in adapters.items()
                     if adapter.source_id == source_id and name not in visited)
    return {**(result or {'status': 'NO_AUTHORIZED_ODDS_ADAPTER', 'quotes': 0, 'fixtures': 0}), 'attempts': attempts}
