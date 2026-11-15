"""Provisional football standings from an explicitly authorized local CSV; no network IO."""
from __future__ import annotations
import csv
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from app.modules.league_intelligence.ingestion import timestamp,validate_document,ImportValidationError

class CSVResearchError(ValueError):
    pass


def build_standings(csv_path: str | Path, *, sport: str, country: str,
                    competition: str, season: str, source: str, source_url: str,
                    as_of: str, permitted: bool = False, season_start: str | None = None,
                    season_end: str | None = None) -> dict:
    if permitted is not True:
        raise CSVResearchError('Explicit permission confirmation required')
    if not isinstance(sport,str) or sport.strip().casefold()!='football':
        raise CSVResearchError('This adapter supports football only')
    try:
        cutoff=timestamp(as_of)
    except ImportValidationError as exc:
        raise CSVResearchError(str(exc)) from exc
    path=Path(csv_path)
    if not path.is_file() or path.stat().st_size>30_000_000:
        raise CSVResearchError('CSV missing or exceeds 30MB')
    totals=defaultdict(lambda:dict(played=0,won=0,drawn=0,lost=0,goals_for=0,goals_against=0,points=0))
    seen=set();names={};dates=[];forms=defaultdict(list)
    try:
        with path.open(encoding='utf-8-sig',newline='') as stream:
            reader=csv.DictReader(stream)
            required={'Date','HomeTeam','AwayTeam','FTHG','FTAG','FTR'}
            if not required.issubset(reader.fieldnames or []):
                raise CSVResearchError('Missing required match-result columns')
            for line,match in enumerate(reader,2):
                if not any(match.values()):continue
                try:
                    date_str=match['Date'].strip()
                    try:match_date=datetime.strptime(date_str,'%d/%m/%Y').replace(tzinfo=timezone.utc)
                    except ValueError:match_date=datetime.strptime(date_str,'%d/%m/%y').replace(tzinfo=timezone.utc)
                    # A date-only CSV cannot prove a match finished earlier on the cutoff day.
                    if match_date+timedelta(days=1)>cutoff:continue
                    home,away=match['HomeTeam'].strip(),match['AwayTeam'].strip()
                    h,a=home.casefold(),away.casefold()
                    hg,ag=int(match['FTHG']),int(match['FTAG'])
                    result=match['FTR'].strip().upper()
                    if not home or not away or h==a or min(hg,ag)<0:raise ValueError('invalid teams or scores')
                    if result not in {'H','D','A'} or result!=('H' if hg>ag else 'A' if ag>hg else 'D'):
                        raise ValueError('result inconsistent with score')
                    key=(match_date.date(),h,a)
                    if key in seen:raise ValueError('duplicate fixture')
                    seen.add(key);names.setdefault(h,home);names.setdefault(a,away)
                except (ValueError,TypeError,AttributeError) as exc:
                    raise CSVResearchError(f'Invalid result at CSV row {line}: {exc}') from exc
                dates.append(match_date.date())
                for name,gf,ga in ((h,hg,ag),(a,ag,hg)):
                    row=totals[name]
                    row['played']+=1;row['goals_for']+=gf;row['goals_against']+=ga
                    row['won' if gf>ga else 'lost' if gf<ga else 'drawn']+=1
                    row['points']+=3 if gf>ga else 1 if gf==ga else 0
                    forms[name].append((match_date,line,'W' if gf>ga else 'L' if gf<ga else 'D'))
    except (UnicodeError,csv.Error,OSError) as exc:
        raise CSVResearchError(f'Unable to read CSV: {exc}') from exc
    if not dates or len(totals)<2:
        raise CSVResearchError('No completed matches before cutoff')
    ordered=sorted(totals.items(),key=lambda p:(-p[1]['points'],-(p[1]['goals_for']-p[1]['goals_against']),-p[1]['goals_for'],p[0]))
    entries=[dict(club=names[name],position=i,**stats,form=''.join(r[2] for r in sorted(forms[name])[-5:])) for i,(name,stats) in enumerate(ordered,1)]
    doc=dict(sport=sport.strip(),country=country,competition=competition,season=season,source=source,source_url=source_url,
             as_of=cutoff.isoformat(),view='overall',official=False,entries=entries,
             provenance=dict(input_file=path.name,input_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),completed_matches=len(dates),
                             first_match_date=min(dates).isoformat(),last_match_date=max(dates).isoformat(),
                             methodology='3/1/0 provisional standings; official deductions and tie-breakers not included',
                             cutoff_policy='Date-only rows are included after their entire UTC calendar day has elapsed',
                             limitation='CSV does not prove when results or later corrections became known; independent review is required',
                             status='UNVERIFIED_COMPUTED'))
    if season_start is not None:doc['season_start']=season_start
    if season_end is not None:doc['season_end']=season_end
    try:validate_document(doc)
    except ImportValidationError as exc:raise CSVResearchError(str(exc)) from exc
    return doc
