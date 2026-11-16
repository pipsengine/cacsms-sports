"""Booking Codes dashboard checks; responses are isolated browser test fixtures."""
import json,os,subprocess
from pathlib import Path
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parents[1];BASE=os.getenv('CACSMS_UI_URL','http://localhost:5173')


def main():
    def sidebar(s):
        start=s.index('<aside id="main-sidebar"');return s[start:s.index('</aside>',start)+8]
    assert sidebar((ROOT/'apps/web/src/App.tsx').read_text())==sidebar(subprocess.check_output(['git','show','HEAD:apps/web/src/App.tsx'],cwd=ROOT).decode())
    stamp='2026-11-16T12:00:00Z'
    rows=[dict(id='ticket'+str(i),ticket_id='ticket'+str(i),programme='accumulator',status='VERIFIED' if i<2 else 'BLOCKED' if i==2 else 'PROVIDER_UNAVAILABLE',code='EXTERNAL-TEST-'+str(i) if i<2 else None,provider='Test Provider' if i<2 else None,odds='6.24',legs=5,created_at=stamp,verified_at=stamp if i<2 else None,evidence_url='https://example.org/evidence' if i<2 else None,reason=None if i<2 else 'SOURCE_UNAVAILABLE') for i in range(4)]
    data=dict(mode='PAPER',summary=dict(total=4,prepared=3,booked=2,failed=1,success_rate=66.7),config=dict(mode='PAPER',provider='NOT_CONFIGURED',auto_booking=False,max_retries=None,retry_interval_seconds=None,verification='RECORDED_EXTERNAL_EVIDENCE',daily_cap=None,code_format='EXTERNAL_ONLY'),runtime=dict(worker_online=True),rows=rows,total=4,sample_limit=200,
     checks=[dict(name=n,passed=2,total=4,rate=50) for n in ['Ticket Integrity','Market & Odds Check','Provider Validation','Risk & Exposure Control']],history=[dict(id='event',ticket_id='ticket0',at=stamp,action='EXTERNAL_CODE_RECORDED',status='VERIFIED',reason=None)],failed_items=[dict(id='fail1',ticket_id='ticket2',at=stamp,reason='TEST_PROVIDER_REJECTED')],
     analytics=dict(window_days=30,bookings=2,success_rate=66.7,average_odds=6.24,average_legs=5,paper_roi=None,trend=[dict(date='2026-11-15',verified=1,failed=1,success_rate=50),dict(date='2026-11-16',verified=1,failed=0,success_rate=100)],by_programme=[dict(programme='accumulator',tickets=4,verified=2,awaiting=2)]),
     pipeline=[dict(name=n,detail=d,status='VERIFIED' if i in (0,1,4) else 'NOT_CONFIGURED') for i,(n,d) in enumerate([('Fetch','Prepared'),('Validate','Betslip'),('Submit','Bookmaker'),('Verify','Code'),('Record','Database'),('Notify','Programmes')])],readiness=dict(status='PROVIDER_NOT_CONFIGURED',blockers=['No provider configured'],next_booking_at=None),systems=[dict(name=n,status='NOT_CONFIGURED') for n in ['Ticket Feed','Betslip Formatter','Bookmaker Integration','Code Verification','Retry & Queue Manager','Platform Scheduler']],lifecycle=[dict(name=n,detail='Test recorded phase',status='NOT_CONFIGURED') for n in ['Qualified Ticket','Betslip Preparation','Booking Submission','Code Verification','Booking Recorded']],notice='Test external verification metadata only.')
    with sync_playwright() as p:
        b=p.chromium.launch();page=b.new_page(viewport={'width':1672,'height':941});errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        def respond(route):
            result=data if route.request.url.endswith('/overview') else dict(ticket_id='ticket0',status='PAPER_PREPARED',codes=[dict(id='code1',code='EXTERNAL-TEST-0',provider='Test Provider',verified_at=stamp,evidence_url='https://example.org/evidence')],audit=[dict(action='booking.verified',at=stamp,detail={'mode':'PAPER'})])
            route.fulfill(status=200,content_type='application/json',body=json.dumps(result))
        page.route('**/sports/booking-workspace/**',respond)
        page.goto(BASE+'/sports/booking-codes');page.locator('.bc-recent tbody tr').first.wait_for()
        assert page.locator('.bc-tabs button').count()==6
        assert page.locator('.bc-pipeline li').count()==6
        assert page.locator('.bc-lifecycle li').count()==5
        assert page.locator('.bc-chart').count()==1
        assert page.get_by_role('button',name='Sync Qualified Tickets',exact=True).count()==0
        assert 'Unavailable' in page.locator('.bc-readiness').inner_text()
        page.locator('.bc-recent .bc-code').first.click()
        page.get_by_role('dialog',name='Booking evidence').wait_for()
        page.get_by_role('heading',name='Verified Code Records').wait_for()
        assert page.get_by_role('link',name='Verification evidence').get_attribute('href')=='https://example.org/evidence'
        page.get_by_role('button',name='Close booking details').click()
        page.locator('.bc-tabs').get_by_role('button',name='Booking Register',exact=True).click()
        page.get_by_label('Search booking records',exact=True).fill('EXTERNAL-TEST-1')
        assert page.locator('.bc-register tbody tr').count()==1
        page.locator('.bc-tabs').get_by_role('button',name='Verification Rules',exact=True).click()
        assert page.locator('.bp-rules article').count()==6
        page.locator('.bc-tabs').get_by_role('button',name='Booking History',exact=True).click()
        assert 'External code recorded' in page.locator('.bp-card tbody').inner_text()
        page.locator('.bc-tabs').get_by_role('button',name='Failed Items',exact=True).click()
        assert 'TEST_PROVIDER_REJECTED' in page.locator('.bc-failures').inner_text()
        page.locator('.bc-tabs').get_by_role('button',name='Programme Analytics',exact=True).click()
        assert 'Programme Distribution' in page.locator('.bc-analytics-view').inner_text()
        page.locator('.bc-tabs').get_by_role('button',name='Overview',exact=True).click()
        page.evaluate('''()=>{const original=fetch;window.fetch=async(...args)=>{await new Promise(r=>setTimeout(r,500));return original(...args)};window.bookingOverview=document.querySelector('.bc-overview');window.dispatchEvent(new Event('online'));}''')
        page.wait_for_timeout(100);assert page.locator('.bc-recent tbody tr').count()==4
        page.wait_for_timeout(700);assert page.evaluate('window.bookingOverview.isConnected')
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        (ROOT/'artifacts').mkdir(exist_ok=True);page.screenshot(path=str(ROOT/'artifacts/booking-test-desktop.png'),full_page=True,animations='disabled')
        page.set_viewport_size({'width':390,'height':844});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(ROOT/'artifacts/booking-test-mobile.png'),full_page=True,animations='disabled')
        assert not errors,errors
        b.close()
    print('PASS: sidebar preserved; six tabs, verified evidence detail, search, failures, analytics, lifecycle, stable refresh, responsive overflow.')

if __name__=='__main__':main()
