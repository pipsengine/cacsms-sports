"""Deep Research layout and stable-refresh checks using isolated test responses."""
import json,os,subprocess
from datetime import datetime,timedelta,timezone
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
BASE=os.getenv('CACSMS_UI_URL','http://localhost:5173')


def main():
    with sync_playwright() as p:
        b=p.chromium.launch();page=b.new_page(viewport={'width':1672,'height':941});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        keys=['head_to_head','recent_form','injuries','lineups','match_statistics','official_result','team_news','standings']
        stamp='2026-11-10T12:00:00Z'
        names=['Head-to-Head','Team Form','Injuries & Availability','Probable Lineups','Match Statistics','Official Results','Club News & Reports','League Standings']
        second_verified=[False]
        only_past=[False]
        now=datetime.now(timezone.utc)
        kicks={'f1':(now+timedelta(days=1)).isoformat(),'f2':(now-timedelta(days=13)).isoformat(),'f3':(now+timedelta(hours=1)).isoformat()}
        statuses={'f1':'SCHEDULED','f2':'COMPLETED_UNVERIFIED','f3':'CANCELLED'}
        def entry(name,rank):return dict(club=name,rank=rank,played=10,wins=7,draws=2,losses=1,goals_for=20,goals_against=9,goal_difference=11,points=23,form='WWDLW')
        def team(name,rank):return dict(name=name,standing=entry(name,rank),form='WWDLW',average_goals=2,clean_sheet_pct=40,sample_size=10)
        def workspace(ident):
            def section_status(key):
                if ident=='f1' or (key=='recent_form' and second_verified[0]):return 'VERIFIED'
                return 'PROVISIONAL' if key in ('recent_form','match_statistics') else 'NO_VERIFIED_EVIDENCE'
            return dict(fixture=dict(id=ident,home='Test Home' if ident=='f1' else 'Other Home',away='Test Away',kickoff_at=kicks[ident],status=statuses[ident],matchday=28,competition_id='league',competition='Test League',country='Germany',sport='Football',season_id='season',season='2026/2027'),cutoff=stamp,dossier_id='dossier',version=1,status='VERIFIED' if ident=='f1' else 'INCOMPLETE',last_research_at=stamp,
             sections=[dict(key=k,name=n,count=1 if section_status(k) in ('VERIFIED','PROVISIONAL') else 0,recorded_count=1 if section_status(k) in ('VERIFIED','PROVISIONAL') else 0,required=k!='official_result',status=section_status(k),details={}) for k,n in zip(keys,names)],evidence=[dict(id=k,section=k,observed_at=stamp,source_name='Test source',source_url='https://example.org/evidence',status='RECORDED_AUTHORIZED',data={'fact':k}) for k in keys],verified_sections=7 if ident=='f1' else int(second_verified[0]),total_sections=7,sample_limit=500,
             summary=dict(home=team('Test Home',1),away=team('Test Away',2),top_two=[entry('Test Home',1),entry('Test Away',2)],table_mode='source_snapshot',table_warning=None,head_to_head=[dict(id='meeting',kickoff_at=stamp,home='Test Home',away='Test Away',home_score=1,away_score=1)]),
             research_readiness=dict(reason='Partial data',next_action='Obtain independent review.',providers=[dict(source_id='s1',provider='Test source',issues=['partial sample'],sides={})]),
             metrics=dict(research_runs=5,fixtures_researched=2,evidence_items=7),sources=dict(authorized=1,recorded=1,online=None),
             runtime=dict(status='OPERATING',worker_online=True,next_run_at=stamp,stages=dict(acquire='VERIFIED',research='INSUFFICIENT_DATA',analyse='PENDING'),stage_errors={'research':dict(code='PROVISIONAL_RESEARCH_ONLY' if ident=='f1' else 'PROVIDER_FAILED',reason='Provider failure')}),message='Test evidence context')
        def respond(route):
            url=route.request.url
            if '/workspace/' in url:data=workspace(url.split('/workspace/')[1].split('?')[0])
            else:
                endpoint=url.split('/catalog/')[1].split('?')[0]
                data={'sports':[dict(id='sport',name='Football')],'countries':[dict(name='Germany')],'leagues':[dict(id='league',name='Test League')],'seasons':[dict(id='season',label='2026/2027',is_current=True)],'fixtures':[dict(id=i,home='Test Home' if i=='f1' else 'Other Home',away='Test Away',kickoff=kicks[i],status=statuses[i]) for i in (['f2','f3'] if only_past[0] else ['f2','f3','f1'])]}[endpoint]
            route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
        page.route('**/research/catalog/**',respond);page.route('**/research/workspace/**',respond)
        page.route('**/live/stream',lambda route:route.abort())
        page.goto(BASE+'/sports/research');page.locator('.dmr-match').wait_for()
        assert page.get_by_label('Fixture',exact=True).input_value()=='f1'
        assert 'COMPLETED UNVERIFIED' in page.locator('option[value="f2"]').inner_text()
        assert 'WAT' in page.locator('option[value="f2"]').inner_text()
        assert page.locator('.dmr-tabs button').count()==8
        assert page.locator('.dmr-right .dmr-coverage').count()==8
        assert page.get_by_text('Official Results').count()>=1
        page.locator('.dmr-kickoff b',has_text='Test League — Matchday 28').wait_for()
        for label in ['Latest Capture','Next Controller Update','Dossier Created','Sources (Authorized)']:assert page.get_by_text(label,exact=True).count()==1,label
        assert page.get_by_text('Provisional research saved.',exact=False).count()==1
        readiness=page.locator('.dmr-readiness')
        assert not readiness.evaluate('(e)=>e.open')
        readiness.locator('summary').click()
        assert readiness.get_by_text('Test source:',exact=False).is_visible()
        readiness.locator('summary').click()
        assert page.locator('.sidebar .nav-link').count()==29
        assert page.locator('.dmr-filters button').count()==0
        for tab in ['H2H','Form','Injuries','Lineups','Statistics','Club News','Evidence','Overview']:
            page.get_by_role('tab',name=tab,exact=True).click()
            if tab!='Overview':assert page.locator('.dmr-evidence-list article').count()>=1
        page.get_by_label('Fixture',exact=True).select_option('f2')
        page.locator('.dmr-home h3',has_text='Other Home').wait_for()
        assert page.get_by_text("This fixture's kickoff has passed.",exact=False).is_visible()
        assert page.locator('.dmr-error',has_text='PROVIDER_FAILED').is_visible()
        assert page.get_by_text('0% verified',exact=True).is_visible()
        assert page.get_by_text('0 verified · 2 provisional of 7 pre-match sections',exact=True).is_visible()
        assert page.locator('.dmr-coverage-bar.provisional').count()==2
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
        second_verified[0]=True
        page.get_by_text('14% verified',exact=True).wait_for(timeout=15000)
        assert page.get_by_text('14% verified',exact=True).is_visible()
        assert page.get_by_text('1 verified · 1 provisional of 7 pre-match sections',exact=True).is_visible()
        assert page.locator('.dmr-coverage-bar.provisional').count()==1
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        for width in (1366,1280,1024):
            page.set_viewport_size({'width':width,'height':768})
            assert not page.evaluate('document.documentElement.scrollWidth>innerWidth'),width
            assert page.locator('.dmr-filters').evaluate('(e)=>e.getBoundingClientRect().bottom<window.innerHeight'),width
            if width>=1101:
                assert page.locator('.dmr-match').evaluate('(e)=>e.getBoundingClientRect().top<window.innerHeight'),width
                assert page.locator('.dmr-kpis').evaluate('(e)=>e.scrollWidth<=e.clientWidth'),width
        page.set_viewport_size({'width':1672,'height':941})
        (ROOT/'artifacts').mkdir(exist_ok=True);page.evaluate('window.scrollTo(0,0)');page.screenshot(path=str(ROOT/'artifacts/deep-research-test-desktop.png'),full_page=True,animations='disabled')
        page.set_viewport_size({'width':390,'height':844});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        assert page.locator('.dmr-kickoff').evaluate('(e)=>e.getBoundingClientRect().top>=document.querySelector(".dmr-home").getBoundingClientRect().bottom')
        page.screenshot(path=str(ROOT/'artifacts/deep-research-test-mobile.png'),full_page=True,animations='disabled')
        only_past[0]=True
        page.goto(BASE+'/sports/research')
        page.get_by_text('No upcoming scheduled fixtures are currently recorded',exact=False).wait_for()
        assert page.get_by_label('Fixture',exact=True).input_value()==''
        page.get_by_label('Fixture',exact=True).select_option('f2')
        page.locator('.dmr-home h3',has_text='Other Home').wait_for()
        assert page.get_by_text("This fixture's kickoff has passed.",exact=False).is_visible()
        assert not errors,errors
        b.close()
    print('PASS: tabs, fixture filters/deep links, evidence, stable and automatic coverage refresh, responsive layout, no browser errors.')

if __name__=='__main__':main()
