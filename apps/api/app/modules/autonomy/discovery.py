"""Discover real fixtures from explicitly configured authorized JSON feeds."""
import json,os
from datetime import datetime,timezone
from pydantic import BaseModel,Field,ValidationError
from sqlalchemy import select
from app.db import models as m
from app.modules.acquisition.jobs import fetch_json,validate_feed_url
from app.modules.ingestion.service import ingest_fixture

class FixtureRecord(BaseModel):
 sport_name:str=Field(min_length=1,max_length=100)
 competition_name:str=Field(min_length=1,max_length=200)
 home:str=Field(min_length=1,max_length=200)
 away:str=Field(min_length=1,max_length=200)
 kickoff_at:datetime
 source_url:str
 source_reference:str=Field(min_length=1,max_length=1000)
 country:str|None=Field(default=None,max_length=100)
 season:str|None=Field(default=None,max_length=100)


def configuration():
 value=json.loads(os.getenv('SPORTS_DISCOVERY_FEEDS_JSON') or '{}')
 if not isinstance(value,dict) or len(value)>5 or any(not isinstance(k,str) or not isinstance(v,str) for k,v in value.items()):
  raise ValueError('Discovery configuration must map up to five registered source IDs to HTTPS feed URLs')
 return value


def collect(session_factory,fetcher=fetch_json):
 report={'configured_feeds':0,'fetched_feeds':0,'fixtures':0,'errors':[]}
 try:feeds=configuration()
 except (ValueError,TypeError):
  report['errors'].append({'code':'INVALID_DISCOVERY_CONFIGURATION'});return report
 report['configured_feeds']=len(feeds)
 for source_id,url in feeds.items():
  try:
   with session_factory() as db:
    source=db.get(m.Source,source_id)
    if source is None or not source.enabled or source.permission!='AUTHORIZED':
     report['errors'].append({'source_id':source_id,'code':'SOURCE_NOT_AUTHORIZED'});continue
   validate_feed_url(url,resolve=False)
   payload=fetcher(url)
   records=payload.get('fixtures')
   if not isinstance(records,list) or len(records)>500:raise ValueError('Invalid fixtures envelope')
   report['fetched_feeds']+=1
   for raw in records:
    try:
     item=FixtureRecord.model_validate(raw)
     if item.kickoff_at.tzinfo is None or item.home.strip().casefold()==item.away.strip().casefold():
      raise ValueError('Invalid fixture identity or timezone')
     validate_feed_url(item.source_url,resolve=False)
     with session_factory.begin() as db:
      source=db.get(m.Source,source_id)
      if source is None or not source.enabled or source.permission!='AUTHORIZED':raise PermissionError('Source revoked')
      result=ingest_fixture(db,source.name,item.sport_name.strip(),item.competition_name.strip(),item.home.strip(),item.away.strip(),item.kickoff_at,item.source_url,{'source_reference':item.source_reference})
      fixture=db.get(m.Fixture,result['fixture_id']);competition=db.get(m.Competition,fixture.competition_id)
      if item.country:
       if competition.country and competition.country!=item.country:raise ValueError('Competition country conflict')
       competition.country=item.country
      if item.season:
       season=db.scalar(select(m.CompetitionSeason).where(m.CompetitionSeason.competition_id==competition.id,m.CompetitionSeason.label==item.season))
       if season is None or not season.start_date<=item.kickoff_at.astimezone(timezone.utc).date()<=season.end_date:
        raise ValueError('Unknown season or fixture outside season')
       fixture.season_id=season.id
     report['fixtures']+=1
    except (ValueError,PermissionError,TypeError) as exc:
     report['errors'].append({'source_id':source_id,'code':type(exc).__name__})
  except Exception as exc:
   report['errors'].append({'source_id':source_id,'code':type(exc).__name__})
 report['errors']=report['errors'][:25]
 return report
