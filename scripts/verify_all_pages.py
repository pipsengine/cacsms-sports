"""Playwright acceptance over every sidebar route, using genuine backend responses.

Set CACSMS_UI_URL (default :5173) and optionally CACSMS_API_URL to test an
isolated API process. Requests are forwarded unchanged, never fulfilled with fixtures.
"""
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv('CACSMS_UI_URL', 'http://127.0.0.1:5173')
API = os.getenv('CACSMS_API_URL')


def main():
    output = ROOT / 'artifacts' / 'remediation'
    output.mkdir(parents=True, exist_ok=True)
    navigation = (ROOT / 'apps/web/src/navigation.ts').read_text(encoding='utf-8').split('} as const')[0]
    targets = re.findall(r"\['([^']+)','([^']+)'\]", navigation)
    report = {'pages': [], 'javascript_errors': [], 'api_errors': [], 'responsive': []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.emulate_media(reduced_motion='reduce')
        page.set_default_timeout(20000)
        pending = set()
        page.on('request', lambda request: pending.add(request) if '/api/' in request.url and '/live/stream' not in request.url else None)
        page.on('requestfinished', lambda request: pending.discard(request))
        page.on('requestfailed', lambda request: pending.discard(request))
        def settled():
            deadline = time.monotonic() + 30
            quiet = 0
            while time.monotonic() < deadline:
                page.wait_for_timeout(150)
                quiet = quiet + 1 if not pending else 0
                if quiet >= 2: return
            raise AssertionError('API requests did not settle: ' + str([request.url for request in pending]))
        page.on('pageerror', lambda error: report['javascript_errors'].append(str(error)))
        page.on('response', lambda response: report['api_errors'].append({'status': response.status, 'url': response.url})
                if '/api/' in response.url and response.status >= 500 else None)
        if API:
            def forward(route):
                parsed = urlsplit(route.request.url)
                route.continue_(url=API.rstrip('/') + parsed.path + ('?' + parsed.query if parsed.query else ''))
            page.route('**/api/**', forward)
        page.goto(BASE + '/sports/dashboard', wait_until='domcontentloaded')
        for label, slug in targets:
            try:
                page.locator('#main-sidebar a[href="/sports/' + slug + '"]').click()
                page.wait_for_url('**/sports/' + slug)
                page.locator('main.content').wait_for()
                page.get_by_role('heading', name='Model Intelligence & Governance Centre' if slug=='models' else label, exact=True).first.wait_for()
                settled()
                assert 'Page unavailable' not in page.locator('main.content').inner_text()
                report['pages'].append({'route': slug, 'status': 'PASS'})
            except Exception as exc:
                report['pages'].append({'route': slug, 'status': 'FAIL', 'reason': str(exc)[:300]})
        page.goto(BASE + '/sports/markets', wait_until='domcontentloaded')
        page.get_by_label('Price classification').wait_for()
        settled()
        for classification in ('HISTORICAL', 'RESEARCH_SNAPSHOT', 'FRESH_MARKET'):
            with page.expect_response(lambda response: '/odds-intelligence/observations' in response.url and 'classification=' + classification in response.url, timeout=60000) as response:
                page.get_by_label('Price classification').select_option(classification)
            assert response.value.status == 200
        for width in (390, 768, 1280, 1920):
            page.set_viewport_size({'width': width, 'height': 1000})
            page.wait_for_function("innerWidth < 1024 || document.querySelector('.main').getBoundingClientRect().left >= document.querySelector('.sidebar').getBoundingClientRect().right - 1")
            page.wait_for_timeout(400)
            metrics = page.evaluate('({scroll:document.documentElement.scrollWidth,width:innerWidth})')
            report['responsive'].append({'width': width, 'document_width': metrics['scroll'], 'status': 'PASS' if metrics['scroll'] <= width + 1 else 'FAIL'})
            page.screenshot(path=str(output / f'markets-{width}.png'), full_page=True, animations='disabled')
        browser.close()
    (output / 'ui-tests.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    assert len(report['pages']) == len(targets) and len(targets) >= 29
    assert all(row['status'] == 'PASS' for row in report['pages'] + report['responsive'])
    assert not report['javascript_errors'] and not report['api_errors']


if __name__ == '__main__':
    main()

