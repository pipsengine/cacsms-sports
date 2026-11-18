"""Read-only community tables from licensed provider match data.

These caches never create verified results, reviewed snapshots or prediction inputs.
"""
from datetime import datetime, timedelta
from sqlalchemy import select
from app.db import models as m
from app.modules.research.league import utc


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
    """Cache a provisional Bundesliga table from a complete discovery response."""
    from app.modules.autonomy import openligadb
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
    provider_season = profile.details.get('provider_season', profile.season_label)
    cache_id = 'openligadb:bl1:' + provider_season
    cache = db.get(m.ProviderSyncState, cache_id)
    if cache is None:
        cache = m.ProviderSyncState(id=cache_id, source_id=openligadb.SOURCE_ID, payload={}, failures=0)
        db.add(cache)
    cache.last_full_at = at
    cache.next_check_at = None
    cache.failures = 0
    cache.payload = {'fixtures': len(matches), 'attribution': openligadb.ATTRIBUTION, 'licence_url': openligadb.LICENCE,
                     'table_version': 2, 'community_tables': tables, 'competition_id': profile.competition_id,
                     'season_id': season.id, 'standings_url': openligadb.BASE + '/getmatchdata/bl1/' + provider_season}
    return 'UPDATED' if tables else 'NO_COMPLETED_MATCHES'


def report(db, competition_id, season_id, cutoff, scope):
    if not season_id:
        return None
    caches=db.scalars(select(m.ProviderSyncState).join(m.Source,m.Source.id==m.ProviderSyncState.source_id)
        .where(m.Source.enabled.is_(True),m.Source.permission=='AUTHORIZED',m.ProviderSyncState.last_full_at<=cutoff)
        .order_by(m.ProviderSyncState.last_full_at.desc()))
    for cache in caches:
        payload=cache.payload or {}
        if payload.get('competition_id')!=competition_id or payload.get('season_id')!=season_id:
            continue
        rows=payload.get('community_tables',{}).get(scope)
        if not rows:
            continue
        source=db.get(m.Source,cache.source_id)
        stale = utc(cutoff) - utc(cache.last_full_at) > timedelta(hours=24)
        return dict(mode='community_computed',scope=scope,season_id=season_id,as_of=cutoff,rows=rows,
            warning=('Source data is over 24 hours old. ' if stale else '') + 'Community-source research table, not independently verified or official. Uses 3/1/0 points, goal difference and goals scored; deductions and competition-specific tie-breakers are excluded.',
            source=dict(id=source.id,name=source.name,official=False,captured_at=cache.last_full_at,verified_at=None,
                        source_url=payload['standings_url'],source_reference=cache.id,licence_url=payload.get('licence_url'),
                        attribution=payload.get('attribution')),next_check_at=cache.next_check_at,community_statistics=payload.get('community_tables',{}).get('_statistics'))
    return None
