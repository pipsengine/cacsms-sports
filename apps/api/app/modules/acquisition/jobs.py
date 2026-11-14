"""Durable, fail-closed acquisition jobs for explicitly configured permitted JSON feeds."""
import hashlib,json,os,ipaddress,socket
from datetime import datetime,timedelta,timezone
from urllib.parse import urlparse
from sqlalchemy import select,update,or_
from app.db import models as m
from app.db.base import SessionLocal
from app.modules.acquisition.service import ingest_observation,ALLOWED_SECTIONS

def utcnow():return datetime.now(timezone.utc)
def feed_config():
    config=json.loads((os.getenv('SPORTS_SOURCE_FEEDS_JSON') or '{}'))
    if not isinstance(config,dict):raise ValueError('Feed configuration must be an object')
    return config
def configured_feed(source_id,section):
    feed=feed_config().get(source_id,{})
    if not isinstance(feed,dict) or section not in feed:raise ValueError('No administrator-configured feed for this source and section')
    url=feed[section]
    if not isinstance(url,str):raise ValueError('Feed URL must be a string')
    return url
def validate_feed_url(url,resolve=True):
    parsed=urlparse(url)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError('Only public HTTPS feeds on port 443 are allowed')
    if parsed.fragment:raise ValueError('Fragments are not allowed')
    host=parsed.hostname.lower()
    if host in ('localhost','localhost.localdomain') or host.endswith(('.local','.internal')):
        raise ValueError('Private host forbidden')
    try:
        literal_ip=ipaddress.ip_address(host)
        if not literal_ip.is_global:raise ValueError('Private IP literal forbidden')
    except ValueError as exc:
        if str(exc)=='Private IP literal forbidden':raise
    if resolve:
        try: addresses=socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)
        except OSError as exc:raise ValueError('Feed hostname cannot be resolved') from exc
        if not addresses:raise ValueError('Feed hostname has no addresses')
        for address in addresses:
            ip=ipaddress.ip_address(address[4][0])
            if not ip.is_global:raise ValueError('Feed resolves to a nonpublic address')
    return url
def enqueue(session,source_id,fixture_id,section,period_key):
    source=session.get(m.Source,source_id)
    if source is None or not source.enabled or source.permission!='AUTHORIZED':raise PermissionError('Source not authorized')
    if session.get(m.Fixture,fixture_id) is None:raise ValueError('Unknown fixture')
    if section not in ALLOWED_SECTIONS:raise ValueError('Unsupported research section')
    if not isinstance(period_key,str) or not period_key or len(period_key)>100:raise ValueError('Invalid collection period')
    configured_feed(source_id,section)
    key=hashlib.sha256(f'{source_id}|{fixture_id}|{section}|{period_key}'.encode()).hexdigest()
    existing=session.scalar(select(m.AcquisitionJob).where(m.AcquisitionJob.idempotency_key==key))
    if existing:return {'id':existing.id,'status':existing.status,'duplicate':True}
    job=m.AcquisitionJob(source_id=source_id,fixture_id=fixture_id,section=section,idempotency_key=key)
    session.add(job);session.flush()
    session.add(m.AuditEvent(actor='scheduler',action='acquisition.enqueued',correlation_id=job.id,payload={'section':section,'mode':'PAPER'}))
    return {'id':job.id,'status':job.status,'duplicate':False}
def claim(session,job_id):
    now=utcnow()
    stmt=(update(m.AcquisitionJob).where(m.AcquisitionJob.id==job_id,m.AcquisitionJob.attempts<m.AcquisitionJob.max_attempts,m.AcquisitionJob.next_run_at<=now,or_(m.AcquisitionJob.status.in_(['PENDING','RETRY_SCHEDULED']), (m.AcquisitionJob.status=='RUNNING') & (m.AcquisitionJob.lease_until<now))).values(status='RUNNING',attempts=m.AcquisitionJob.attempts+1,lease_until=now+timedelta(seconds=90),updated_at=now).returning(m.AcquisitionJob.id))
    return session.execute(stmt).scalar_one_or_none() is not None
def fetch_json(url):
    import httpx
    validate_feed_url(url)
    # Environment proxies and redirects are disabled. Production should additionally enforce egress firewall rules.
    with httpx.Client(timeout=httpx.Timeout(12),follow_redirects=False,trust_env=False,headers={'Accept':'application/json','User-Agent':'CACSMS-Research/2.3'}) as client:
        with client.stream('GET',url) as response:
            response.raise_for_status()
            if 300<=response.status_code<400:raise ValueError('Redirected feeds are forbidden')
            data=bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data)>1_000_000:raise ValueError('Feed response exceeds 1 MB')
    payload=json.loads(data)
    if not isinstance(payload,dict) or not payload:raise ValueError('Feed must return a nonempty JSON object')
    return payload
def run_job(job_id,fetcher=fetch_json):
    with SessionLocal.begin() as session:
        if not claim(session,job_id):return {'id':job_id,'status':'NOT_CLAIMED'}
        job=session.get(m.AcquisitionJob,job_id)
        source_id,fixture_id,section=job.source_id,job.fixture_id,job.section
    try:
        url=configured_feed(source_id,section)
        payload=fetcher(url)
        if payload.get('fixture_id')!=fixture_id:raise ValueError('Feed fixture identity mismatch')
        if payload.get('section')!=section:raise ValueError('Feed research section mismatch')
        with SessionLocal.begin() as session:
            job=session.get(m.AcquisitionJob,job_id)
            if job.status!='RUNNING':return {'id':job_id,'status':'STALE'}
            result=ingest_observation(session,source_id=source_id,fixture_id=fixture_id,section=section,source_url=url,observed_at=utcnow(),payload=payload.get('data') if section=='official_result' else payload)
            job.observation_id=result['id'];job.status='COMPLETED';job.lease_until=None;job.updated_at=utcnow();job.error_code=None
            session.add(m.AuditEvent(actor='acquisition-worker',action='acquisition.completed',correlation_id=job_id,payload={'observation_id':result['id'],'mode':'PAPER'}))
        return {'id':job_id,'status':'COMPLETED','observation_id':result['id']}
    except Exception as exc:
        # No secrets or raw response bodies in operational errors.
        with SessionLocal.begin() as session:
            job=session.get(m.AcquisitionJob,job_id)
            if job.status=='RUNNING':
                job.status='FAILED' if job.attempts>=job.max_attempts else 'RETRY_SCHEDULED'
                job.error_code=type(exc).__name__[:80];job.lease_until=None;job.updated_at=utcnow()
                job.next_run_at=utcnow()+timedelta(seconds=min(300,2**job.attempts*10))
                session.add(m.AuditEvent(actor='acquisition-worker',action='acquisition.failed',correlation_id=job_id,payload={'error_code':job.error_code,'status':job.status,'mode':'PAPER'}))
                if job.status=='FAILED':session.add(m.Incident(severity='HIGH',message=f'Acquisition job {job_id} exhausted retry budget'))
        return {'id':job_id,'status':'ERROR','error_code':type(exc).__name__}
