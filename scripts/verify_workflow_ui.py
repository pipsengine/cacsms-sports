"""Browser acceptance checks against a running real backend and frontend.

python scripts/verify_workflow_ui.py
Set CACSMS_UI_URL and optional CACSMS_BROWSER_CHANNEL (e.g. msedge) as needed.
"""
import os,re,json,time
from pathlib import Path
from urllib.parse import urljoin,urlparse,parse_qs
from playwright.sync_api import sync_playwright

BASE=os.getenv('CACSMS_UI_URL','http://localhost:5173').rstrip('/')
ROOT=Path(__file__).resolve().parents[1]
TARGETS=['fixtures','browser','research','match-analysis','predictions','markets','qualification','programmes/singles','tickets','betslip','live-operations','results']


def main():
 with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,channel=os.getenv('CACSMS_BROWSER_CHANNEL') or None)
  page=browser.new_page(viewport={'width':1440,'height':1050});page.set_default_timeout(15000)
  errors=[];bad=[];pending=set()
  def track(request):
   if '/api/' in request.url and '/live/stream' not in request.url:pending.add(request)
  page.on('request',track)
  page.on('requestfinished',lambda request:pending.discard(request))
  page.on('requestfailed',lambda request:pending.discard(request))
  def settled():
   deadline=time.monotonic()+15;quiet=0
   while time.monotonic()<deadline:
    page.wait_for_timeout(150)
    quiet=quiet+1 if not pending else 0
    if quiet>=3:return
   raise AssertionError('API requests did not settle: '+str([request.url for request in pending]))
  page.on('pageerror',lambda error:errors.append(str(error)))
  page.on('response',lambda response:bad.append((response.status,response.url)) if '/api/' in response.url and response.status>=400 else None)
  page.goto(BASE+'/sports/dashboard',wait_until='domcontentloaded')
  stage_links=page.locator('.fd-pipeline .sf-step a.sf-card')
  stage_links.first.wait_for();settled()
  assert stage_links.count()==12
  assert page.locator('.fd-pipeline .sf-arrow').count()==11
  page.get_by_role('region',name='Autonomous operation').wait_for()
  links=stage_links.evaluate_all('(items)=>items.map(x=>x.getAttribute("href"))')
  assert len(links)==12
  for index,href in enumerate(links):
   assert urlparse(href).path=='/sports/'+TARGETS[index]
   page.goto(urljoin(BASE,href),wait_until='domcontentloaded')
   page.locator('.af-top h2' if page.url.split('?')[0].endswith('/fixtures') else '.lsi-topline h2' if page.url.split('?')[0].endswith('/statistics') else '.dmr-header h2' if page.url.split('?')[0].endswith(('/research','/match-analysis','/predictions','/markets','/qualification','/opportunities')) else '.page-heading h1').wait_for();settled()
   query=parse_qs(urlparse(href).query)
   if query.get('run_id'):
    page.locator('.workflow-context .workflow-context-metrics').wait_for()
    assert not page.locator('.workflow-context .error').count()
    assert page.locator('.workflow-step-links').first.locator('a').count()==12
   assert page.locator('.sidebar .nav-link').count()==29
  # Orchestrator renders the same twelve stages as a selectable process flow.
  page.goto(BASE+'/sports/orchestrator',wait_until='domcontentloaded')
  page.locator('.pipeline-workspace .sf-step').first.wait_for();settled()
  assert page.locator('.pipeline-workspace .sf-step').count()==12
  page.locator('.pipeline-workspace button.sf-card').nth(3).click()
  page.locator('.pipeline-stage-detail h3',has_text='Analyse').wait_for()
  # Fixtures & Competitions: real overview data, aggregate process flow and tabs.
  page.goto(BASE+'/sports/fixtures',wait_until='domcontentloaded')
  page.locator('.af-reference-flow li').first.wait_for();settled()
  assert page.locator('.af-reference-flow li').count()==5
  for tab in ('Competitions','Countries','Leagues & Divisions','Research Coverage','Fixtures'):
   page.get_by_role('tab',name=tab).click();settled()
  nav=(ROOT/'apps/web/src/navigation.ts').read_text(encoding='utf-8')
  slugs=re.findall(r"\['[^']+','([^']+)'\]",nav)
  assert len(slugs)==29
  for slug in slugs:
   page.goto(BASE+'/sports/'+slug,wait_until='domcontentloaded')
   page.locator('.af-top h2' if page.url.split('?')[0].endswith('/fixtures') else '.lsi-topline h2' if page.url.split('?')[0].endswith('/statistics') else '.dmr-header h2' if page.url.split('?')[0].endswith(('/research','/match-analysis','/predictions','/markets','/qualification','/opportunities')) else '.page-heading h1').wait_for();settled()
  page.goto(BASE+'/sports/dashboard',wait_until='domcontentloaded')
  page.get_by_role('button',name='Collapse sidebar',exact=True).click();page.wait_for_timeout(300)
  assert page.locator('.main').evaluate('(e)=>e.getBoundingClientRect().left')==0
  page.get_by_role('button',name='Expand sidebar',exact=True).click();page.wait_for_timeout(300)
  for width in (1440,834,390):
   page.set_viewport_size({'width':width,'height':900});page.wait_for_timeout(200)
   assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'),width
  artifacts=ROOT/'artifacts';artifacts.mkdir(exist_ok=True)
  page.screenshot(path=str(artifacts/'pipeline-dashboard-mobile.png'),full_page=True)
  page.set_viewport_size({'width':1440,'height':1050});page.wait_for_timeout(350);page.screenshot(path=str(artifacts/'pipeline-dashboard-desktop.png'),full_page=True)
  browser.close()
  assert not errors,errors
  assert not bad,bad
  print('All 12 stage destinations, 29 pages, context links and responsive layouts passed.')

if __name__=='__main__':main()
