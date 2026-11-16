"""Match Analysis layout check using isolated (mocked) API responses. Values are test fixtures only."""
import json,os
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
BASE=os.getenv('CACSMS_UI_URL','http://localhost:5173')
STAMP='2026-11-16T08:03:00Z'


def team(name,rank,points,form):
    return dict(name=name,standing=dict(club=name,rank=rank,points=points),form=form,sample_size=10)


def analysis(ident,empty=False):
    home,away=('FC Bayern München','1. FC Köln') if ident=='f1' else ('Other Home','Other Away')
    keys=['match_statistics','team_news','injuries','lineups','head_to_head']
    evidence=[dict(id=k+str(i),section=k,observed_at=STAMP,source_name='Test source',source_url='https://example.org/e',status='RECORDED_AUTHORIZED',data={'fact':k}) for i,k in enumerate(keys)]
    row=lambda k,l,h,a,u='',b='VERIFIED_RESULTS':dict(key=k,label=l,home=h,away=a,unit=u,basis=b)
    return dict(fixture=dict(id=ident,home=home,away=away,kickoff_at='2026-11-16T16:30:00Z',status='SCHEDULED',matchday=12,competition_id='league',competition='Bundesliga',country='Germany',sport='Football',season_id='season',season='2026/2027'),
        cutoff=STAMP,status='PARTIAL' if empty else 'VERIFIED',teams=dict(home=team(home,1,68,'WWWDW'),away=team(away,14,12,'LLDWL')),
        probabilities=dict(home=None,draw=None,away=None,model=None,predicted_at=None) if empty else dict(home=82.4,draw=12.1,away=5.5,model='Test 1.0',predicted_at=STAMP),
        expected_goals=None if empty else dict(home=2.71,away=0.82),
        form_metrics=[row('goals_per_match','Goals per Match',2.71,1.08),row('goals_conceded','Goals Conceded',0.86,1.65)]+([] if empty else [row('xg_per_match','xG (Expected Goals)',2.46,1.03,'','FEATURE_SNAPSHOT'),row('xga_per_match','xGA (Expected Against)',0.92,1.74,'','FEATURE_SNAPSHOT')])+[row('clean_sheet_rate','Clean Sheet Rate',43,18,'%')],
        feature_comparison=[] if empty else [row('attack_strength','Attack Strength',94.6,63.1),row('defence_strength','Defence Strength',88.2,56.8),row('midfield_control','Midfield Control',91.3,60.4),row('form_rating','Form Rating',0.88,0.36),row('home_advantage','Home Advantage',0.41,-0.21)],
        head_to_head=[dict(id='m'+str(i),kickoff_at=d,home=h,away=a,home_score=x,away_score=y) for i,(d,h,a,x,y) in enumerate([('2025-04-13T13:30:00Z',home,away,3,1),('2024-11-22T19:30:00Z',away,home,0,2),('2024-04-15T13:30:00Z',home,away,2,0),('2023-11-24T19:30:00Z',away,home,0,1),('2023-05-27T13:30:00Z',home,away,1,1)])],
        summary=[dict(key=k,name=n,status='MISSING' if empty and k in ('tactics','features') else 'COMPUTED' if k=='form' and empty else 'VERIFIED') for k,n in [('statistics','Statistical Analysis'),('form','Team Form Analysis'),('head_to_head','Head-to-Head Analysis'),('availability','Injuries & Lineup Status'),('tactics','Tactical Matchup'),('features','Feature Engineering')]],
        verified_rows=3 if empty else 6,
        evidence_groups=[dict(key='match_statistics',name='Match Statistics',count=6),dict(key='team_news',name='Team News & Injuries',count=4),dict(key='lineups',name='Lineups (Probable)',count=2),dict(key='historical',name='Historical Results',count=5),dict(key='tactics',name='Tactical Analysis',count=0 if empty else 4),dict(key='sources',name='External Sources',count=3)],
        evidence=evidence,sections=[],
        metadata=dict(analysis_id=None if empty else 'MA-2026-11-160428',research_id='r',research_version=1,feature_versions=1,last_analysis_at=None if empty else STAMP,data_freshness_at=STAMP,next_update_at='2026-11-16T08:17:00Z'),
        metrics=dict(analysed_matches=24736,analysis_records=19842,evidence_items=192430,coverage=50.0 if empty else 99.6),
        runtime=dict(status='OPERATING',worker_online=True,next_run_at='2026-11-16T08:17:00Z',stages=dict(acquire='VERIFIED',analyse='VERIFIED')),message='Test analysis context')


def main():
    with sync_playwright() as p:
        b=p.chromium.launch();page=b.new_page(viewport={'width':1672,'height':941});errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        def respond(route):
            url=route.request.url
            if '/match-analysis/fixtures/' in url:
                ident=url.split('/fixtures/')[1].split('?')[0];data=analysis(ident,empty=ident=='f2')
            else:
                endpoint=url.split('/catalog/')[1].split('?')[0]
                data={'sports':[dict(id='sport',name='Football')],'countries':[dict(name='Germany')],'leagues':[dict(id='league',name='Bundesliga')],'seasons':[dict(id='season',label='2026/2027',is_current=True)],
                      'fixtures':[dict(id='f1',home='FC Bayern München',away='1. FC Köln',kickoff='2026-11-16T16:30:00Z',status='SCHEDULED'),dict(id='f2',home='Other Home',away='Other Away',kickoff='2026-11-16T16:30:00Z',status='SCHEDULED')]}[endpoint]
            route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
        page.route('**/research/catalog/**',respond);page.route('**/match-analysis/**',respond)
        page.goto(BASE+'/sports/match-analysis');page.locator('.dmr-match').wait_for()
        page.locator('.dmr-kickoff b',has_text='Bundesliga — Matchday 12').wait_for()
        assert page.locator('.dmr-tabs button').count()==8
        assert page.locator('.ma-insights>div').count()==4
        assert page.get_by_text('BAY: 82.4%').count()==1 and page.get_by_text('KÖL: 5.5%').count()==1
        assert page.locator('.ma-metrics tbody tr').count()==5 and page.locator('.ma-compare tbody tr').count()==5
        assert page.locator('.dmr-right .dmr-coverage').count()==6 and page.locator('.ma-groups>div').count()==6
        assert page.locator('.dmr-h2h>div').count()==5
        assert page.locator('.research-filter-panel, .workflow-context').count()==0
        (ROOT/'artifacts').mkdir(exist_ok=True);page.screenshot(path=str(ROOT/'artifacts/match-analysis-test-desktop.png'),full_page=True,animations='disabled')
        for tab in ['Statistics','Form','Head-to-Head','Lineups','Injuries','Tactics','Evidence','Overview']:
            page.get_by_role('tab',name=tab,exact=True).click()
        page.get_by_label('Fixture',exact=True).select_option('f2')
        page.locator('.dmr-home h3',has_text='Other Home').wait_for()
        assert page.get_by_text('No forecast from an approved (ACTIVE) model exists before the cutoff.').count()==1
        assert page.locator('.ma-compare').count()==0 and page.get_by_text('Computed',exact=True).count()==1
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(200)
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(ROOT/'artifacts/match-analysis-test-mobile.png'),full_page=True,animations='disabled')
        assert not errors,errors
        b.close()
    print('PASS: Match Analysis layout, 8 tabs, insights, form/feature tables, summary, evidence, empty states, desktop/mobile overflow.')

if __name__=='__main__':main()
