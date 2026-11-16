"""Deep Research layout and stable-refresh checks using isolated test responses."""
import json,os,subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
BASE=os.getenv('CACSMS_UI_URL','http://localhost:5173')


def main():
    with sync_playwright() as p:
        b=p.chromium.launch();page=b.new_page(viewport={'width':1672,'height':941});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        keys=['head_to_head','recent_form','injuries','lineups','match_statistics','team_news','standings']
        stamp='2026-11-10T12:00:00Z'
        names=['Head-to-Head','Team Form','Injuries & Availability','Probable Lineups','Match Statistics','Club News & Reports','League Standings']
        def entry(name,rank):return dict(club=name,rank=rank,played=10,wins=7,draws=2,losses=1,goals_for=20,goals_against=9,goal_difference=11,points=23,form='WWDLW')
        def team(name,rank):return dict(name=name,standing=entry(name,rank),form='WWDLW',average_goals=2,clean_sheet_pct=40,sample_size=10)
        def workspace(ident):
            return dict(fixture=dict(id=ident,home='Test Home' if ident=='f1' else 'Other Home',away='Test Away',kickoff_at='2026-11-20T16:00:00Z',status='SCHEDULED',competition_id='league',competition='Test League',country='Germany',sport='Football',season_id='season',season='2026/2027'),cutoff=stamp,dossier_id='dossier',version=1,status='VERIFIED',last_research_at=stamp,
             sections=[dict(key=k,name=n,count=1,status='VERIFIED',details={}) for k,n in zip(keys,names)],evidence=[dict(id=k,section=k,observed_at=stamp,source_name='Test source',source_url='https://example.org/evidence',status='RECORDED_AUTHORIZED',data={'fact':k}) for k in keys],verified_sections=7,total_sections=7,sample_limit=500,
             summary=dict(home=team('Test Home',1),away=team('Test Away',2),top_two=[entry('Test Home',1),entry('Test Away',2)],table_mode='source_snapshot',table_warning=None,head_to_head=[dict(id='meeting',kickoff_at=stamp,home='Test Home',away='Test Away',home_score=1,away_score=1)]),metrics=dict(research_runs=5,fixtures_researched=2,evidence_items=7),sources=dict(authorized=1,recorded=1,online=None),runtime=dict(status='OPERATING',worker_online=True,next_run_at=stamp,stages=dict(acquire='VERIFIED',research='VERIFIED',analyse='VERIFIED')),message='Test evidence context')
        def respond(route):
            url=route.request.url
            if '/workspace/' in url:data=workspace(url.split('/workspace/')[1].split('?')[0])
            else:
                endpoint=url.split('/catalog/')[1].split('?')[0]
                data={'sports':[dict(id='sport',name='Football')],'countries':[dict(name='Germany')],'leagues':[dict(id='league',name='Test League')],'seasons':[dict(id='season',label='2026/2027',is_current=True)],'fixtures':[dict(id=i,home='Test Home' if i=='f1' else 'Other Home',away='Test Away',kickoff='2026-11-20T16:00:00Z',status='SCHEDULED') for i in ['f1','f2']]}[endpoint]
            route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
        page.route('**/research/catalog/**',respond);page.route('**/research/workspace/**',respond)
        page.goto(BASE+'/sports/research');page.locator('.dmr-match').wait_for()
        assert page.locator('.dmr-tabs button').count()==8
        assert page.locator('.dmr-right .dmr-coverage').count()==7
        assert page.locator('.sidebar .nav-link').count()==29
        assert page.locator('.dmr-filters button').count()==0
        for tab in ['H2H','Form','Injuries','Lineups','Statistics','Club News','Evidence','Overview']:
            page.get_by_role('tab',name=tab,exact=True).click()
            if tab!='Overview':assert page.locator('.dmr-evidence-list article').count()>=1
        page.get_by_label('Fixture',exact=True).select_option('f2')
        page.locator('.dmr-home h3',has_text='Other Home').wait_for()
        page.goto(BASE+'/sports/research?fixture_id=f1')
        page.locator('.dmr-home h3',has_text='Test Home').wait_for()
        page.get_by_label('Fixture',exact=True).select_option('f2')
        page.locator('.dmr-home h3',has_text='Other Home').wait_for()
        assert 'fixture_id=' not in page.url
        page.evaluate('''() => {const original=fetch;window.fetch=async(...args)=>{await new Promise(r=>setTimeout(r,600));return original(...args)};window.banner=document.querySelector('.dmr-match');window.dispatchEvent(new Event('online'));}''')
        page.wait_for_timeout(150)
        assert page.locator('.dmr-match').is_visible()
        page.wait_for_timeout(800)
        assert page.evaluate('window.banner.isConnected')
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        (ROOT/'artifacts').mkdir(exist_ok=True);page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(ROOT/'artifacts/deep-research-test-desktop.png'),full_page=True,animations='disabled')
        page.set_viewport_size({'width':390,'height':844});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        assert page.locator('.dmr-kickoff').evaluate('(e)=>e.getBoundingClientRect().top>=document.querySelector(".dmr-home").getBoundingClientRect().bottom')
        page.screenshot(path=str(ROOT/'artifacts/deep-research-test-mobile.png'),full_page=True,animations='disabled')
        assert not errors,errors
        b.close()
    print('PASS: eight tabs, fixture filters/deep links, evidence, stable refresh, desktop/mobile overflow, no browser errors.')

if __name__=='__main__':main()
