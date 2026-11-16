"""Orchestrator design/interaction checks with isolated response fixtures."""
import json,os,subprocess
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];BASE=os.getenv('CACSMS_UI_URL','http://localhost:5173')
KEYS=['discover','acquire','research','analyse','predict','evaluate','qualify','allocate','prepare','verify','monitor','reconcile']
NAMES=['Discover','Acquire','Research','Analyse','Predict','Evaluate','Qualify','Allocate','Prepare','Verify','Monitor','Reconcile']


def main():
    def sidebar(s):
        start=s.index('<aside id="main-sidebar"');return s[start:s.index('</aside>',start)+8]
    assert sidebar((ROOT/'apps/web/src/App.tsx').read_text())==sidebar(subprocess.check_output(['git','show','HEAD:apps/web/src/App.tsx'],cwd=ROOT).decode())
    stamp='2026-11-16T12:00:00Z'
    def run(ident):return dict(id=ident,fixture_id='fixture',mode='PAPER',status='WAITING_FOR_DATA',created_at=stamp,updated_at='2026-11-16T12:06:24Z',stages=[dict(position=i+1,stage_key=k,name=n,status='VERIFIED' if i<5 or i==10 else 'WAITING_FOR_DATA' if i in (5,11) else 'PENDING',error='Waiting for source data' if i==5 else None,retry_count=1 if i==5 else 0,duration_ms=20+i if i<6 else None,started_at=stamp if i<6 else None,finished_at=stamp if i<5 else None,evidence_ids=['evidence1'] if i==1 else [],input={'test_input':k},output={'test_output':k} if i<5 else {},input_version=3,output_version=1 if i<5 else 0,output_reference='receipt'+str(i) if i<5 else None,quality_score=None,failure_code='NO_FRESH_MARKET' if i==5 else None,next_stage=KEYS[i+1] if i<11 else None,contract={'stage':k.upper(),'status':'PENDING'}) for i,(k,n) in enumerate(zip(KEYS,NAMES))])
    runs=[run('a8a348d1-test'),run('7d66ebf9-test')]
    definitions=[dict(key=k,name=n,position=i+1,inputs=['stored_forecasts','market_data'] if i==5 else ['canonical_input'],validation_rules=['source_backed','fresh_market'],expected_output='validated_output',dependencies=[KEYS[i-1]] if 0<i<10 else [],dependency_policy='INDEPENDENT' if i>9 else 'VALIDATED_UPSTREAM',sla_ms=None,outcome='Only validated output proceeds.') for i,(k,n) in enumerate(zip(KEYS,NAMES))]
    counts={'runs':0,'mutations':0}
    with sync_playwright() as p:
        b=p.chromium.launch();page=b.new_page(viewport={'width':1672,'height':941});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        def respond(route):
            url=urlparse(route.request.url);path=url.path
            if route.request.method!='GET':counts['mutations']+=1
            if path.endswith('/contracts'):data=definitions
            elif path.endswith('/runs'):data=runs;counts['runs']+=1
            elif path.endswith('/history'):data=[dict(id='h1',stage=parse_qs(url.query).get('stage',['evaluate'])[0].upper(),status='WAITING_FOR_DATA',attempt=2,started_at=stamp,completed_at=stamp,duration_ms=40,input_version=3,output_version=0,output_reference=None,failure_code='NO_FRESH_MARKET',failure_reason='No source market',details={})]
            elif path.endswith('/evidence'):data=[dict(id='evidence1',type='Observation',status='RECORDED_REFERENCE',record={'payload':{'test_evidence':'source-backed'}})]
            else:data=run(path.split('/')[-1])
            route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
        page.route('**/sports/pipeline/**',respond)
        page.route('**/sports/autonomy/status',lambda r:r.fulfill(status=200,content_type='application/json',body='{"worker_online":true,"status":"OPERATING"}'))
        page.goto(BASE+'/sports/orchestrator');page.locator('.eo-flow .eo-stage').first.wait_for()
        assert page.locator('.eo-flow .eo-stage').count()==12
        page.locator('.eo-flow .eo-stage').nth(3).click()
        assert page.locator('.eo-detail h3').inner_text()=='Analyse'
        page.get_by_role('button',name='List View',exact=True).click();assert page.locator('.eo-flow.list .eo-stage').count()==12
        page.get_by_role('button',name='Graph View',exact=True).click()
        page.locator('.eo-flow .eo-stage').nth(5).click()
        assert 'market_data' in page.locator('.eo-contract').inner_text()
        page.get_by_role('button',name='Inputs & Outputs',exact=True).click();assert 'test_input' in page.locator('.eo-json').inner_text()
        page.locator('.eo-flow .eo-stage').nth(1).click();page.get_by_role('button',name='Evidence (1)',exact=True).click()
        page.locator('.eo-evidence summary').first.wait_for();page.locator('.eo-evidence summary').click()
        assert 'test_evidence' in page.locator('.eo-evidence pre').inner_text()
        page.get_by_role('button',name='Execution History',exact=True).click();page.locator('.eo-history tbody tr').wait_for()
        assert 'NO_FRESH_MARKET' in page.locator('.eo-history').inner_text()
        page.locator('.eo-run-list>button').nth(1).click();assert '7d66ebf9-test' in page.url
        page.get_by_label('Search pipeline runs',exact=True).fill('a8a348d1');assert page.locator('.eo-run-list>button').count()==1
        page.get_by_label('Search pipeline runs',exact=True).fill('')
        page.get_by_role('button',name='Pause updates',exact=True).click();before=counts['runs']
        page.evaluate("window.dispatchEvent(new Event('online'))");page.wait_for_timeout(200);assert counts['runs']==before
        assert 'autonomous worker continues' in page.locator('.eo-notice').inner_text()
        page.get_by_role('button',name='Resume updates',exact=True).click();page.wait_for_timeout(200)
        assert counts['runs']>before
        page.goto(BASE+'/sports/orchestrator?run_id=outside-list&stage=research');page.locator('.eo-detail h3',has_text='Research').wait_for()
        assert '#outside-' in page.locator('.eo-run-metadata').inner_text()
        page.goto(BASE+'/sports/orchestrator?run_id=a8a348d1-test&stage=evaluate')
        page.locator('.eo-detail h3',has_text='Evaluate').wait_for()
        page.get_by_role('button',name='Stage Data Contract',exact=True).click()
        page.evaluate('''()=>{const original=fetch;window.fetch=async(...args)=>{await new Promise(r=>setTimeout(r,500));return original(...args)};window.flow=document.querySelector('.eo-flow');window.dispatchEvent(new Event('online'));}''')
        page.wait_for_timeout(150);assert page.locator('.eo-flow .eo-stage').count()==12
        page.wait_for_timeout(750);assert page.evaluate('window.flow.isConnected')
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        (ROOT/'artifacts').mkdir(exist_ok=True);page.screenshot(path=str(ROOT/'artifacts/orchestrator-test-desktop.png'),full_page=True,animations='disabled')
        page.set_viewport_size({'width':390,'height':844});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(ROOT/'artifacts/orchestrator-test-mobile.png'),full_page=True,animations='disabled')
        assert not errors,errors
        assert counts['mutations']==0
        b.close()
    print('PASS: preserved sidebar; 12 stages, graph/list, run/stage deep links, four detail tabs, display-only pause, stable refresh, responsive layout; GET requests only.')

if __name__=='__main__':main()
