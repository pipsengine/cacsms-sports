"""Evidence-bound research dossiers. No unsupported statistics are inferred."""
from sqlalchemy import select,func
from app.db import models as m
SECTIONS=('standings','recent_form','head_to_head','team_news','lineups','injuries','match_statistics')
# UNAVAILABLE = explicitly marked unavailable (corroborated declaration or research deadline);
# it completes a mandatory dimension without inventing data.
VALID={'VERIFIED','UNAVAILABLE','MISSING','PENDING','CONFLICTED'}
COMPLETE={'VERIFIED','UNAVAILABLE'}

def build_dossier(session,fixture_id,sections,evidence_ids,*,at=None):
    fixture=session.get(m.Fixture,fixture_id)
    if fixture is None:raise ValueError('Fixture does not exist')
    if not isinstance(sections,dict) or set(sections)-set(SECTIONS):raise ValueError('Unknown research section')
    if not isinstance(evidence_ids,list) or len(set(evidence_ids))!=len(evidence_ids):raise ValueError('Evidence IDs must be a unique list')
    evidence={o.id:o for o in session.scalars(select(m.Observation).where(m.Observation.id.in_(evidence_ids))).all()} if evidence_ids else {}
    if len(evidence)!=len(evidence_ids):raise ValueError('Research evidence not found')
    if any(o.fixture_id!=fixture_id for o in evidence.values()):raise ValueError('Evidence belongs to a different fixture')
    if any(not (session.get(m.Source,o.source_id).enabled and session.get(m.Source,o.source_id).permission=='AUTHORIZED') for o in evidence.values()):raise ValueError('Research evidence source is not authorized')
    normalized={}
    for key in SECTIONS:
        entry=sections.get(key,{'status':'MISSING'})
        if not isinstance(entry,dict) or entry.get('status') not in VALID:raise ValueError('Invalid section status: '+key)
        refs=entry.get('evidence_ids',[])
        if not isinstance(refs,list) or any(ref not in evidence for ref in refs):raise ValueError('Section has unknown evidence references: '+key)
        if entry['status']=='VERIFIED' and not refs:raise ValueError('Verified section requires evidence: '+key)
        normalized[key]={'status':entry['status'],'evidence_ids':refs,'details':entry.get('details',{})}
    status='VERIFIED' if all(s['status'] in COMPLETE for s in normalized.values()) and any(s['status']=='VERIFIED' for s in normalized.values()) else 'PARTIAL'
    version=(session.scalar(select(func.max(m.Research.version)).where(m.Research.fixture_id==fixture_id)) or 0)+1
    dossier=m.Research(fixture_id=fixture_id,version=version,status=status,sections=normalized,evidence_ids=evidence_ids)
    
    if at is not None:dossier.created_at=at
    session.add(dossier);session.flush()
    return {'id':dossier.id,'fixture_id':fixture_id,'version':version,'status':status,'sections':normalized,'evidence_ids':evidence_ids}
