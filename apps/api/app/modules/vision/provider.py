"""Optional real multimodal inference via an administrator-configured OpenAI-compatible endpoint.
No credentials, no inference; output is always untrusted until evidence validation.
"""
import base64,hashlib,json,os
from pathlib import Path
import httpx

ALLOWED_SECTIONS={'standings','recent_form','head_to_head','team_news','lineups','injuries','match_statistics'}

def validate_inference(result:dict, screenshot:bytes, fixture_id:str, source_url:str)->dict:
    if not screenshot.startswith(b'\x89PNG\r\n\x1a\n'):raise ValueError('Not a PNG image')
    if not isinstance(result,dict):raise ValueError('Inference must be JSON object')
    digest=hashlib.sha256(screenshot).hexdigest()
    if result.get('evidence_sha256')!=digest:raise ValueError('Vision output does not reference exact screenshot hash')
    if result.get('fixture_id')!=fixture_id:raise ValueError('Vision fixture identity mismatch')
    if result.get('source_url')!=source_url:raise ValueError('Vision source URL mismatch')
    observations=result.get('observations')
    if not isinstance(observations,list) or len(observations)>30:raise ValueError('Invalid observations')
    cleaned=[]
    for item in observations:
        if not isinstance(item,dict) or item.get('section') not in ALLOWED_SECTIONS:raise ValueError('Unknown research section')
        if not isinstance(item.get('value'),(str,int,float)) or not str(item['value']).strip():raise ValueError('Missing observed value')
        if not isinstance(item.get('visible_text'),str) or not item['visible_text'].strip():raise ValueError('Visible text citation required')
        if len(item['visible_text'])>500 or len(str(item['value']))>500:raise ValueError('Observation too large')
        cleaned.append({'section':item['section'],'value':item['value'],'visible_text':item['visible_text'],'confidence':item.get('confidence')})
    return {'evidence_sha256':digest,'fixture_id':fixture_id,'source_url':source_url,'observations':cleaned,'status':'EXTRACTED_UNVERIFIED','requires_independent_verification':True}

async def infer_screenshot(image:bytes,fixture_id:str,source_url:str)->dict:
    endpoint=os.getenv('SPORTS_VISION_ENDPOINT','').strip()
    token=os.getenv('SPORTS_VISION_API_KEY','').strip()
    model=os.getenv('SPORTS_VISION_MODEL','').strip()
    if not endpoint or not token or not model:raise RuntimeError('Vision provider is not configured')
    from urllib.parse import urlsplit
    u=urlsplit(endpoint)
    if u.scheme!='https' or not u.hostname or u.username or u.password:raise ValueError('Vision endpoint must use credential-free HTTPS URL')
    # Explicit host allowlist; never send screenshots to arbitrary endpoints.
    hosts={x.strip().lower() for x in os.getenv('SPORTS_VISION_ALLOWED_HOSTS','').split(',') if x.strip()}
    if u.hostname.lower() not in hosts:raise PermissionError('Vision provider host not approved')
    from app.modules.vision.security import validate_destination
    validate_destination(endpoint,list(hosts))
    digest=hashlib.sha256(image).hexdigest()
    instruction=('Extract ONLY facts visibly present in the screenshot. Never guess. Return JSON with '
      'evidence_sha256, fixture_id, source_url, observations array. Each observation has section '
      '(standings/recent_form/head_to_head/team_news/lineups/injuries/match_statistics), '
      'value, visible_text and confidence. If uncertain return empty observations. '
      f'Exact evidence_sha256={digest}; fixture_id={fixture_id}; source_url={source_url}.')
    payload={'model':model,'temperature':0,'response_format':{'type':'json_object'},'messages':[{'role':'user','content':[{'type':'text','text':instruction},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(image).decode()}}]}]}
    async with httpx.AsyncClient(timeout=45,follow_redirects=False,trust_env=False) as client:
        response=await client.post(endpoint,headers={'Authorization':'Bearer '+token},json=payload)
        response.raise_for_status()
        raw=response.json()['choices'][0]['message']['content']
    return validate_inference(json.loads(raw),image,fixture_id,source_url)
