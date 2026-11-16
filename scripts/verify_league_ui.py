"""League UI contract checks with isolated browser response fixtures.
Run against Vite: python scripts/verify_league_ui.py
These responses are test data only and are never installed in the app/database.
"""
import json, os, subprocess
from pathlib import Path
from urllib.parse import urlparse,parse_qs
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1]
BASE=os.getenv('CACSMS_UI_URL','http://localhost:5173')


def main():
    current=(ROOT/'apps/web/src/App.tsx').read_text(encoding='utf-8')
    original=subprocess.check_output(['git','show','HEAD:apps/web/src/App.tsx'],cwd=ROOT).decode()
    def sidebar(text):
        start=text.index('<aside id="main-sidebar"')
        return text[start:text.index('</aside>',start)+8]
    assert sidebar(current)==sidebar(original),'Shared sidebar markup changed'
    assert 'useState<string[]>(()=>Object.keys(navigation))' in current
    rows=[dict(rank=i,club=f'Test Club {i:02d}',played=14,wins=8,draws=3,losses=3,goals_for=22,goals_against=12,goal_difference=10,points=30-i,form='WWDLW') for i in range(1,21)]
    stamp='2026-11-11T11:00:00+00:00'
    seen=[]
    def respond(route):
        url=urlparse(route.request.url);endpoint=url.path.split('/catalog/')[-1] if '/catalog/' in url.path else url.path.split('/standings/')[1];q=parse_qs(url.query);seen.append((endpoint,q))
        data={
          'sports':[dict(id='sport1',name='Football')],
          'countries':[dict(name='Nigeria')],
          'competitions':[dict(id='league1',name='Test Premier League',country='Nigeria')],
          'seasons':[dict(id='season1',label='2026/2027',is_current=True)],
          'table':dict(classification='source_snapshot',mode='overall',rows=rows,source=dict(name='Test source',captured_at=stamp,verified_at=stamp,source_url='https://example.org/evidence',official=True)),
          'fixtures':[dict(id=f'f{i}',home='Test Club 01',away='Test Club 02',kickoff=f'2026-11-{i+1:02d}T12:00:00Z',home_score=2,away_score=1) for i in range(5)],
          'coverage':dict(views={key:dict(status='VERIFIED',verified_count=1,pending_count=0) for key in ['overall','home','away']}),
          'standings/history':[],
          'top-two':dict(clubs=rows[:2]),
          'analytics':dict(sample_size=5,average_goals=3.14,home_win_pct=100,draw_pct=0,away_win_pct=0,goals_by_date=[dict(day='2026-11-01',value=3)],note='Test sample'),
          'history':dict(syncs=[dict(id='run1',status='COMPLETED',started_at=stamp,valid_rows=5,rejected_rows=0)]),
          'health':dict(status='DATA_AVAILABLE',authorized_sources=1,source_count=1,last_successful_sync=stamp,next_sync=None,failures=0)
        }[endpoint]
        route.fulfill(status=200,content_type='application/json',body=json.dumps(data))
    with sync_playwright() as p:
        browser=p.chromium.launch()
        page=browser.new_page(viewport={'width':1672,'height':941})
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        page.route('**/research/catalog/**',respond)
        page.route('**/sports/standings/**',respond)
        page.goto(BASE+'/sports/statistics')
        page.locator('.lsi-table-scroll tbody tr').first.wait_for()
        assert page.locator('.lsi-table-scroll tbody tr').count()==20
        assert page.locator('.lsi-team-link b').last.inner_text()=='Test Club 20'
        assert page.locator('.lsi-form .draw').first.evaluate('(e)=>getComputedStyle(e).backgroundColor')=='rgb(245, 158, 11)'
        assert any(e=='table' and q.get('all_rows')==['true'] for e,q in seen)
        assert page.locator('.sidebar .nav-link').count()==29
        page.locator('.lsi-search-details summary').click()
        page.get_by_role('textbox',name='Search clubs').fill('Club 20')
        assert page.locator('.lsi-team-link').count()==1
        page.get_by_role('textbox',name='Search clubs').fill('')
        for name,scope in [('Home','home'),('Away','away'),('Overall','overall')]:
            with page.expect_response(lambda r:'/standings/table?' in r.url and f'mode={scope}' in r.url):
                page.locator('.lsi-tabs').get_by_role('button',name=name,exact=True).click()
            page.locator('.lsi-table-scroll tbody tr').first.wait_for()
        page.locator('.lsi-tabs').get_by_role('button',name='Historical Standings',exact=True).click()
        page.get_by_role('heading',name='Source snapshot coverage').wait_for()
        page.locator('.lsi-tabs').get_by_role('button',name='Top Two Clubs',exact=True).click()
        assert page.locator('.lsi-top-team').count()==2
        page.locator('.lsi-tabs').get_by_role('button',name='League Analytics',exact=True).click()
        assert '100.0%' in page.locator('.lsi-analytics').inner_text()
        page.locator('.lsi-tabs').get_by_role('button',name='Overall',exact=True).click()
        page.get_by_label('Country',exact=True).select_option('Nigeria')
        page.locator('.lsi-table-scroll tbody tr').first.wait_for()
        assert any(e=='competitions' and q.get('country')==['Nigeria'] for e,q in seen)
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        (ROOT/'artifacts').mkdir(exist_ok=True)
        page.evaluate('window.scrollTo(0,0)')
        page.screenshot(path=str(ROOT/'artifacts/league-populated-test.png'),full_page=True,animations='disabled')
        page.set_viewport_size({'width':390,'height':844})
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        assert page.get_by_role('button',name='Auto Sync',exact=True).count()==0
        page.evaluate('''() => {
          const original=window.fetch;
          window.fetch=async (...args)=>{await new Promise(r=>setTimeout(r,500));return original(...args)};
          window.standingsRows=[...document.querySelectorAll('.lsi-table-scroll tbody tr')];
          window.dispatchEvent(new Event('online'));
        }''')
        page.wait_for_timeout(150)
        assert page.locator('.lsi-table-scroll tbody tr').count()==20
        assert page.locator('select[aria-label="Season"] option').count()==2
        page.wait_for_timeout(650)
        assert page.evaluate('window.standingsRows.every(row=>row.isConnected)')
        page.route('**/sports/standings/table?**',lambda r:r.fulfill(status=503,content_type='application/json',body='{"detail":"Test service unavailable"}'))
        page.evaluate("window.dispatchEvent(new Event('online'))")
        page.get_by_role('alert').filter(has_text='Test service unavailable').wait_for()
        assert page.locator('.lsi-table-scroll tbody tr').count()==20
        assert not errors,errors
        browser.close()
    print('PASS: unchanged sidebar, filters, API scopes, full table, amber draws, stable automatic refresh, search, history, analytics, desktop/mobile overflow and error state.')

if __name__=='__main__':main()

