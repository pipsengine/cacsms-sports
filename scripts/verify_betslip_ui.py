"""Betslip dashboard acceptance checks; isolated responses never enter product data."""
import json,os,subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];BASE=os.getenv('CACSMS_UI_URL','http://localhost:5173')


def main():
    def sidebar(s):
        a=s.index('<aside id="main-sidebar"');return s[a:s.index('</aside>',a)+8]
    assert sidebar((ROOT/'apps/web/src/App.tsx').read_text())==sidebar(subprocess.check_output(['git','show','HEAD:apps/web/src/App.tsx'],cwd=ROOT).decode())
    stamp='2026-11-16T12:00:00Z'
    rows=[dict(id=f'slip{i}',ticket_id=f'ticket{i}',programme='accumulator',status='PAPER_PREPARED',bookmaker='Test Provider',combined_odds='6.24',leg_count=2,created_at=stamp,reasons=[],verification=[],selections=[dict(qualification_id=f'q{i}{j}',fixture_id=f'f{i}{j}',fixture=f'Test Home {j} vs Test Away {j}',market='1X2',outcome='HOME',odds='2.5') for j in range(2)]) for i in range(6)]
    data=dict(mode='PAPER',summary=dict(recorded=6,prepared=6,failed=0,preparation_rate=100,average_legs=2),config=dict(mode='PAPER',format='Provider-neutral',ticket_source='REGISTERED_TICKETS',max_odds_age_seconds=900,paid_wagers_enabled=False,programmes={k:dict(min_legs=1 if k=='singles' else 2,max_legs=1 if k=='singles' else 12,max_odds='1000',daily_cap=5) for k in ['accumulator','singles','jackpot','draws','rollover']}),runtime=dict(worker_online=True,status='OPERATING',next_run_at=stamp),pipeline=[dict(name=n,detail=d,status='VERIFIED' if i<5 else 'NOT_CONFIGURED') for i,(n,d) in enumerate([('Fetch','Tickets'),('Verify','Markets'),('Format','Betslip'),('Risk Check','Odds / Limits'),('Prepare','Paper'),('Queue','Booking')])],rows=rows,total=6,sample_limit=200,checks=[dict(name=n,passed=6,total=6,rate=100) for n in ['Ticket Integrity','Market & Odds Check','Risk & Exposure Control']],history=[dict(id='run1',run_id='pipeline1',stage='prepare',status='VERIFIED',started_at=stamp,failure_code=None,reason=None,attempt=1)],analytics=[dict(programme='accumulator',recorded=6,prepared=6,failed=0,preparation_rate=100)],readiness=dict(status='AWAITING_VERIFICATION',provider_booking='NOT_CONFIGURED',ready_slip_ids=[]),systems=[dict(name=n,status='WAITING_FOR_DATA') for n in ['Ticket Feed','Market Data & Odds','Betslip Formatter','Risk Controls','Scheduler (Auto Prepare)']],note='Test recorded paper data only.')
    with sync_playwright() as p:
        browser=p.chromium.launch();page=browser.new_page(viewport={'width':1672,'height':941});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        def respond(route):
            result=data if route.request.url.endswith('/overview') else {**rows[0],'audit':[dict(event='paper_ticket.prepared',detail={'mode':'PAPER'},created_at=stamp)]}
            route.fulfill(status=200,content_type='application/json',body=json.dumps(result))
        page.route('**/sports/betslip-preparation/**',respond)
        page.goto(BASE+'/sports/betslip');page.locator('.bp-recent tbody tr').first.wait_for()
        assert page.locator('.bp-tabs button').count()==5
        assert page.locator('.bp-recent tbody tr').count()==5
        assert page.locator('.bp-pipeline li').count()==6
        assert page.locator('.bp-preview tbody tr').count()==2
        page.get_by_label('Paper stake',exact=True).fill('50')
        assert '312.00' in page.locator('.bp-return').inner_text()
        page.locator('.bp-recent .bp-record').first.click()
        page.get_by_role('dialog',name='Betslip details').wait_for()
        page.get_by_role('heading',name='Audit Trail').wait_for()
        page.get_by_role('button',name='Close details').click()
        page.locator('.bp-tabs').get_by_role('button',name='Betslip List',exact=True).click()
        page.get_by_label('Search betslips',exact=True).fill('ticket5')
        assert page.locator('.bp-card tbody tr').count()==1
        page.locator('.bp-tabs').get_by_role('button',name='Verification Rules',exact=True).click()
        page.get_by_label('Programme rules',exact=True).select_option('singles')
        assert '1–1 legs' in page.locator('.bp-rules').inner_text()
        page.locator('.bp-tabs').get_by_role('button',name='Preparation History',exact=True).click()
        assert 'prepare' in page.locator('.bp-card tbody').inner_text().lower()
        page.locator('.bp-tabs').get_by_role('button',name='Programme Analytics',exact=True).click()
        assert 'Accumulator' in page.locator('.bp-card tbody').inner_text()
        page.locator('.bp-tabs').get_by_role('button',name='Overview',exact=True).click()
        page.evaluate('''()=>{const original=fetch;window.fetch=async(...a)=>{await new Promise(r=>setTimeout(r,500));return original(...a)};window.overview=document.querySelector('.bp-overview');window.dispatchEvent(new Event('online'));}''')
        page.wait_for_timeout(100);assert page.locator('.bp-recent tbody tr').count()==5
        page.wait_for_timeout(750);assert page.evaluate('window.overview.isConnected')
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        (ROOT/'artifacts').mkdir(exist_ok=True);page.screenshot(path=str(ROOT/'artifacts/betslip-test-desktop.png'),full_page=True,animations='disabled')
        page.set_viewport_size({'width':390,'height':844});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(ROOT/'artifacts/betslip-test-mobile.png'),full_page=True,animations='disabled')
        assert not errors,errors
        browser.close()
    print('PASS: sidebar unchanged; five tabs, recorded detail/audit, paper calculator, rules, history, stable refresh, desktop/mobile layouts.')

if __name__=='__main__':main()
