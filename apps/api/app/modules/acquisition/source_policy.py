"""Source permission policy shared by every outbound path (browser/vision capture, feeds, open-data collectors).

Sources whose published terms prohibit automated access are recorded here with the evidence that was checked,
registered as PROHIBITED (disabled) sources, and refused at every network choke point. A prohibition can only be
lifted by recording the operator's express written consent reference in SPORTS_SOURCE_CONSENT
(e.g. "betexplorer.com=Livesport licence 2027-001"), never by configuration alone.
"""
import os
from datetime import datetime,timezone
from urllib.parse import urlsplit
from sqlalchemy import select,func
from app.db import models as m

PROHIBITED={
 'betexplorer.com':{
  'name':'BetExplorer','operator':'Livesport s.r.o.','terms_url':'https://www.betexplorer.com/terms-of-service.php','checked_at':'2026-11-16',
  'reason':'Terms of Service prohibit scraping, aggregation, database extraction and automated requests without express written consent',
  'clauses':['"you are not permitted to use our content available on the Website by embedding, aggregating, scraping or recreating it without our express consent"',
             '"no extraction (copying) or exploitation ... of the Database Content or of a qualitatively or quantitatively substantial part thereof is permitted without our express consent"',
             '"You must not burden our server on which the Website is hosted with automated requests"'],
  'robots':'robots.txt additionally disallows /bookmaker/, /redirect/ and ?year=, ?page=, ?match=, ?stage= style URLs',
  'alternative':'OpenLigaDB (ODbL API) and Football-Data.co.uk (published CSVs) via autonomy/open_intelligence'},
}


def consents():
 out={}
 for item in os.getenv('SPORTS_SOURCE_CONSENT','').split(','):
  if '=' in item:
   host,ref=item.split('=',1)
   if host.strip() and ref.strip():out[host.strip().lower()]=ref.strip()
 return out


def prohibition(host):
 host=(host or '').lower().rstrip('.')
 for domain,entry in PROHIBITED.items():
  if (host==domain or host.endswith('.'+domain)) and domain not in consents():return {'domain':domain,**entry}
 return None


def assert_permitted(url):
 """Raise PermissionError for any URL on a source whose terms prohibit automated access."""
 entry=prohibition(urlsplit(str(url)).hostname)
 if entry:raise PermissionError(f"{entry['name']} is prohibited: {entry['reason']} ({entry['terms_url']}, checked {entry['checked_at']})")
 return url


def source_id_for(domain):
 from uuid import uuid5,NAMESPACE_URL
 return str(uuid5(NAMESPACE_URL,'prohibited-source:'+domain))


def register_prohibited_sources(db):
 """Idempotently record prohibited sources as disabled PROHIBITED providers with an audit trail."""
 changed=[]
 for domain,entry in PROHIBITED.items():
  consented=domain in consents()
  source=db.get(m.Source,source_id_for(domain)) or db.scalar(select(m.Source).where(m.Source.name==entry['name']))
  if consented or (source is not None and source.permission=='PROHIBITED' and not source.enabled):continue
  if source is None:
   source=m.Source(id=source_id_for(domain),name=entry['name'],permission='PROHIBITED',enabled=False);db.add(source);db.flush()
  else:source.permission='PROHIBITED';source.enabled=False
  db.add(m.AuditEvent(actor='source-policy',action='source.prohibited',correlation_id=source.id,
                      payload={'domain':domain,**{k:v for k,v in entry.items() if k!='name'}}))
  changed.append(domain)
 return changed


def registry(db,at=None):
 """Per-source permission, sync and freshness rows for Source Intelligence (no inferred status)."""
 at=at or datetime.now(timezone.utc)
 from app.modules.research.league import utc
 from app.modules.autonomy.open_intelligence import GROUPS
 rows=[]
 for source in db.scalars(select(m.Source).order_by(m.Source.name)):
  states=db.scalars(select(m.ProviderSyncState).where(m.ProviderSyncState.source_id==source.id)).all()
  syncs=[s.last_full_at for s in states if s.last_full_at]
  nexts=[s.next_check_at for s in states if s.next_check_at]
  observations=db.scalar(select(func.count()).select_from(m.Observation).where(m.Observation.source_id==source.id)) or 0
  latest=db.scalar(select(func.max(m.Observation.observed_at)).where(m.Observation.source_id==source.id))
  results=db.scalar(select(func.count()).select_from(m.ResultEvidence).where(m.ResultEvidence.source_id==source.id)) or 0
  domain=next((d for d,e in PROHIBITED.items() if source.id==source_id_for(d) or source.name==e['name']),None)
  entry=PROHIBITED.get(domain) if domain else None
  status='PROHIBITED' if source.permission=='PROHIBITED' else 'ACTIVE' if source.enabled and source.permission=='AUTHORIZED' else 'DISABLED'
  rows.append({'source':source.name,'status':status,'permission':source.permission,
               'last_sync':max(syncs) if syncs else None,'next_sync':min(nexts) if nexts else None,
               'observations':observations,'freshness_minutes':round((at-utc(latest)).total_seconds()/60) if latest else None,
               'verified_result_evidence':results,'independence_group':GROUPS.get(source.id),
               'sync_failures':sum(s.failures or 0 for s in states),
               'restriction':entry['reason'] if entry and status=='PROHIBITED' else None,
               'terms_url':entry['terms_url'] if entry else None,'terms_checked':entry['checked_at'] if entry else None,
               'id':source.id})
 return rows
