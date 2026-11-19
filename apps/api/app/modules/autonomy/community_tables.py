"""Read-only community tables from licensed provider match data.

These caches never create verified results, reviewed snapshots or prediction inputs.
"""
from datetime import datetime, timedelta, timezone
from sqlalchemy import select
from app.db import models as m
from app.modules.research.league import utc

SUPPORTED_SHORTCUTS = frozenset(('bl1', 'bl2', 'bl3'))
QUARANTINED_TABLES = {
    'openligadb:pl:2026': 'OpenLigaDB Premier League standings conflict with another source and require review',
    'openligadb:la1:2026': 'OpenLigaDB La Liga feed contains clubs from another competition',
}


def quarantine_reason(cache_id):
    return QUARANTINED_TABLES.get(cache_id)


def discovery_cache_id(shortcut, season):
    if shortcut not in SUPPORTED_SHORTCUTS or not str(season).isdigit():
        raise ValueError('UNSUPPORTED_STANDINGS_PROFILE')
    return 'openligadb:' + shortcut + ':' + str(season)


def sportsdb_cache_id(provider_key, season):
    return 'sportsdb-table:' + str(provider_key) + ':' + str(season)


def cache_sportsdb_table(db, profile, records, at):
    """Store only validated overall rows; the provider may truncate the table."""
    from app.modules.autonomy import fixture_providers as providers
    season = profile.details.get('provider_season', profile.season_label)
    cache_id = sportsdb_cache_id(profile.provider_key, season)
    cache = db.get(m.ProviderSyncState, cache_id)
    if cache is None:
        cache = m.ProviderSyncState(id=cache_id, source_id=providers.SPORTSDB_ID, payload={}, failures=0)
        db.add(cache)
    if not records:
        cache.payload = {**cache.payload, 'competition_id': profile.competition_id,
                         'table_status': 'NO_DATA', 'table_error': None}
        return 'NO_DATA'
    if not profile.season_id:
        raise ValueError('STANDINGS_SEASON_UNMAPPED')
    columns = {'rank': 'intRank', 'played': 'intPlayed', 'wins': 'intWin', 'draws': 'intDraw',
               'losses': 'intLoss', 'goals_for': 'intGoalsFor', 'goals_against': 'intGoalsAgainst',
               'goal_difference': 'intGoalDifference', 'points': 'intPoints'}
    rows, ranks, teams, groups, updated = [], set(), set(), set(), []
    for raw in records:
        if str(raw.get('idLeague')) != profile.provider_key or raw.get('strSeason') != season:
            raise ValueError('STANDINGS_IDENTITY_MISMATCH')
        name = raw.get('strTeam')
        team_id = str(raw.get('idTeam') or '')
        if not isinstance(name, str) or not name.strip() or not team_id.isdigit():
            raise ValueError('INVALID_STANDINGS_TEAM')
        row = {'club': name.strip()}
        for field, column in columns.items():
            value = raw.get(column)
            if not isinstance(value, (str, int)) or isinstance(value, bool) or not str(value).lstrip('-').isdigit():
                raise ValueError('INVALID_STANDINGS_NUMBER')
            row[field] = int(value)
        if (row['rank'] < 1 or any(row[k] < 0 for k in ('played', 'wins', 'draws', 'losses', 'goals_for', 'goals_against'))
            or row['played'] != row['wins'] + row['draws'] + row['losses']
            or row['goal_difference'] != row['goals_for'] - row['goals_against']):
            raise ValueError('INCONSISTENT_STANDINGS_ROW')
        if row['rank'] in ranks or team_id in teams or row['club'].casefold() in teams:
            raise ValueError('DUPLICATE_STANDINGS_ROW')
        ranks.add(row['rank']); teams.update((team_id, row['club'].casefold()))
        groups.add(str(raw.get('strGroup') or '').strip())
        form = raw.get('strForm')
        if isinstance(form, str) and all(c in 'WDL' for c in form):
            row['form'] = list(form)
        stamp = raw.get('dateUpdated')
        if stamp:
            parsed = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            parsed = parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
            if parsed > at:
                raise ValueError('FUTURE_STANDINGS_UPDATE')
            updated.append(parsed)
        rows.append(row)
    if len(groups) > 1:
        raise ValueError('MULTIPLE_STANDINGS_GROUPS')
    cache.last_full_at = at
    cache.failures = 0
    cache.payload = {'competition_id': profile.competition_id, 'season_id': profile.season_id,
                     'table_status': 'UPDATED', 'table_error': None,
                     'community_tables': {'overall': sorted(rows, key=lambda row: row['rank'])},
                     'partial_source_table': True, 'provider_updated_at': min(updated).isoformat() if len(updated) == len(rows) else None,
                     'standings_url': 'https://www.thesportsdb.com/docs_api_guide',
                     'attribution': 'Data from TheSportsDB', 'licence_url': 'https://www.thesportsdb.com/docs_terms_of_use.php'}
    return 'UPDATED'


def build_tables(matches, at):
    tables={scope:{} for scope in ('overall','home','away')}
    games=[]
    for match in matches:
        home,away=match['team1']['teamName'],match['team2']['teamName']
        for table in tables.values():
            for team in (home,away):
                table.setdefault(team,dict(club=team,played=0,wins=0,draws=0,losses=0,goals_for=0,goals_against=0,points=0,form=[]))
        kickoff=datetime.fromisoformat(match['matchDateTimeUTC'].replace('Z','+00:00'))
        if match.get('matchIsFinished') is not True or kickoff>at:
            continue
        # The provider explicitly documents semantic result kinds. Never guess a final score
        # from a half-time entry, array order, or a provider-specific numeric type ID.
        finals=[r for r in (match.get('matchResults') or []) if r.get('resultTypeKind')=='After90Minutes']
        if len(finals)!=1:
            continue
        h,a=finals[0].get('pointsTeam1'),finals[0].get('pointsTeam2')
        if type(h) is not int or type(a) is not int or min(h,a)<0:
            continue
        games.append((kickoff,match['matchID'],home,away,h,a))
    for _,_,home,away,h,a in sorted(games):
        for team,gf,ga,side in ((home,h,a,'home'),(away,a,h,'away')):
            for scope in ('overall',side):
                row=tables[scope][team]
                row['played']+=1;row['goals_for']+=gf;row['goals_against']+=ga
                result='W' if gf>ga else 'L' if gf<ga else 'D'
                row[{'W':'wins','D':'draws','L':'losses'}[result]]+=1
                row['points']+=3 if result=='W' else 1 if result=='D' else 0
                row['form']=(row['form']+[result])[-5:]
    result={}
    for scope,teams in tables.items():
        rows=list(teams.values())
        for row in rows:row['goal_difference']=row['goals_for']-row['goals_against']
        rows.sort(key=lambda row:(-row['points'],-row['goal_difference'],-row['goals_for'],row['club']))
        for rank,row in enumerate(rows,1):row['rank']=rank
        result[scope]=rows
    by_date={}
    for kickoff,_,_,_,h,a in sorted(games):
        by_date.setdefault(kickoff.date().isoformat(),[]).append(h+a)
    result['_statistics']=dict(matches=len(games),home_wins=sum(h>a for *_,h,a in games),
        away_wins=sum(h<a for *_,h,a in games),draws=sum(h==a for *_,h,a in games),
        goals_trend=[dict(day=day,value=sum(scores)/len(scores)) for day,scores in list(by_date.items())[-5:]])
    return result


def cache_discovery_table(db, profile, matches, at):
    """Cache a provisional German league table from a discovery response."""
    from app.modules.autonomy import openligadb
    provider_season = profile.details.get('provider_season', profile.season_label)
    cache_id = discovery_cache_id(profile.provider_key, provider_season)
    if not matches:
        raise ValueError('EMPTY_STANDINGS_FEED')
    normalized, _, _ = openligadb.normalize(matches, at)
    if len({match['matchID'] for match in matches}) != len(matches):
        raise ValueError('DUPLICATE_STANDINGS_MATCH_ID')
    identities = {(row['kickoff'], row['home'].strip().casefold(), row['away'].strip().casefold()) for row in normalized}
    if len(identities) != len(normalized):
        raise ValueError('DUPLICATE_STANDINGS_FIXTURE')
    for match, row in zip(matches, normalized):
        if type(match.get('matchIsFinished')) is not bool:
            raise ValueError('INVALID_STANDINGS_MATCH_STATUS')
        if not match['matchIsFinished']:
            continue
        if datetime.fromisoformat(row['kickoff']) > at:
            raise ValueError('FUTURE_FINISHED_STANDINGS_MATCH')
        results = match.get('matchResults')
        if not isinstance(results, list):
            raise ValueError('INVALID_STANDINGS_FINAL_SCORE')
        finals = [r for r in results if isinstance(r, dict) and r.get('resultTypeKind') == 'After90Minutes']
        if len(finals) != 1 or any(type(finals[0].get(k)) is not int or finals[0][k] < 0 for k in ('pointsTeam1', 'pointsTeam2')):
            raise ValueError('INVALID_STANDINGS_FINAL_SCORE')
    dates = [datetime.fromisoformat(row['kickoff']).date() for row in normalized]
    season = db.get(m.CompetitionSeason, profile.season_id) if profile.season_id else None
    if season is not None and season.competition_id != profile.competition_id:
        raise ValueError('STANDINGS_SEASON_UNMAPPED')
    if season is None:
        season = db.scalar(select(m.CompetitionSeason).where(m.CompetitionSeason.competition_id == profile.competition_id,
                                                              m.CompetitionSeason.label == profile.season_label))
    if season is None:
        season = m.CompetitionSeason(competition_id=profile.competition_id, label=profile.season_label,
                  start_date=min(dates), end_date=max(dates), is_current=min(dates) <= at.date() <= max(dates))
        db.add(season); db.flush()
    else:
        season.start_date = min(season.start_date, min(dates))
        season.end_date = max(season.end_date, max(dates))
    profile.season_id = season.id
    tables = build_tables(matches, at)
    if not tables['_statistics']['matches']:
        tables = {}
    cache = db.get(m.ProviderSyncState, cache_id)
    if cache is None:
        cache = m.ProviderSyncState(id=cache_id, source_id=openligadb.SOURCE_ID, payload={}, failures=0)
        db.add(cache)
    cache.last_full_at = at
    cache.next_check_at = None
    cache.failures = 0
    cache.payload = {'fixtures': len(matches), 'attribution': openligadb.ATTRIBUTION, 'licence_url': openligadb.LICENCE,
                     'table_version': 2, 'community_tables': tables, 'competition_id': profile.competition_id,
                     'season_id': season.id, 'standings_url': openligadb.BASE + '/getmatchdata/' + profile.provider_key + '/' + provider_season,
                     'latest_result_at': max((row['kickoff'] for match, row in zip(matches, normalized) if match['matchIsFinished']), default=None)}
    return 'UPDATED' if tables else 'NO_COMPLETED_MATCHES'


def report(db, competition_id, season_id, cutoff, scope):
    if not season_id:
        return None
    caches=list(db.scalars(select(m.ProviderSyncState).join(m.Source,m.Source.id==m.ProviderSyncState.source_id)
        .where(m.Source.enabled.is_(True),m.Source.permission=='AUTHORIZED',m.ProviderSyncState.last_full_at<=cutoff)
        .order_by(m.ProviderSyncState.last_full_at.desc())))
    caches.sort(key=lambda cache: bool((cache.payload or {}).get('partial_source_table')))
    quarantined = [quarantine_reason(cache.id) for cache in caches
                   if (cache.payload or {}).get('competition_id') == competition_id
                   and (cache.payload or {}).get('season_id') == season_id and quarantine_reason(cache.id)]
    for cache in caches:
        payload=cache.payload or {}
        if quarantine_reason(cache.id):
            continue
        if payload.get('competition_id')!=competition_id or payload.get('season_id')!=season_id:
            continue
        rows=payload.get('community_tables',{}).get(scope)
        if not rows:
            continue
        source=db.get(m.Source,cache.source_id)
        stale = utc(cutoff) - utc(cache.last_full_at) > timedelta(hours=24)
        partial = payload.get('partial_source_table', False)
        updated = payload.get('provider_updated_at')
        provider_stale = updated and utc(cutoff) - utc(datetime.fromisoformat(updated)) > timedelta(hours=24)
        warning = ('Partial provider table; coverage is not established and the free tier returns at most five rows. Not official or independently verified. Home/away tables are unavailable. '
                   + ('Provider last updated: ' + updated + '. ' if updated else 'Provider update time unavailable. ')
                   if partial else 'Community-source research table, not independently verified or official. Uses 3/1/0 points, goal difference and goals scored; deductions and competition-specific tie-breakers are excluded.')
        if partial and payload.get('table_status') == 'NO_DATA':
            warning += 'The latest provider check returned no table; this is the last available capture.'
        if not partial and payload.get('latest_result_at'):
            warning += ' Latest included result: ' + payload['latest_result_at'] + '. The feed may omit results or teams.'
        if quarantined:
            warning += ' Quarantined source: ' + ' '.join(quarantined)
        return dict(mode='community_partial' if partial else 'community_computed',scope=scope,season_id=season_id,as_of=cutoff,rows=rows,
            warning=('Source data is over 24 hours old. ' if stale or provider_stale else '') + warning,
            source=dict(id=source.id,name=source.name,official=False,captured_at=cache.last_full_at,verified_at=None,
                        source_url=payload['standings_url'],source_reference=cache.id,licence_url=payload.get('licence_url'),
                        attribution=payload.get('attribution')),next_check_at=cache.next_check_at,community_statistics=payload.get('community_tables',{}).get('_statistics'))
    return None
