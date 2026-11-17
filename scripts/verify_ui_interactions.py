"""Read-only tab interactions plus real request loading/network-failure states."""
import json
import os
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv('CACSMS_UI_URL', 'http://127.0.0.1:5173')
TABS = ','.join('.' + name + ' button' for name in ('dmr-tabs','af-tabs','bp-tabs','diag-tabs','lsi-tabs','mr-tabs','mgi-tabs','pa-tabs','dataset-tabs'))


def main():
    navigation = (ROOT / 'apps/web/src/navigation.ts').read_text(encoding='utf-8').split('} as const')[0]
    targets = re.findall(r"\['([^']+)','([^']+)'\]", navigation)
    report = {'tabs': [], 'javascript_errors': [], 'states': []}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.set_default_timeout(20000)
        page.emulate_media(reduced_motion='reduce')
        page.on('pageerror', lambda error: report['javascript_errors'].append(str(error)))
        for _, slug in targets:
            page.goto(BASE + '/sports/' + slug, wait_until='domcontentloaded')
            page.locator('main.content').wait_for()
            page.wait_for_timeout(350)
            names = page.locator(TABS).all_text_contents()
            for name in names:
                button = page.locator(TABS).filter(has_text=re.compile('^' + re.escape(name) + '$')).first
                if not button.is_visible() or not button.is_enabled(): continue
                try:
                    button.click()
                    page.wait_for_timeout(150)
                    assert page.locator('main.content').is_visible()
                    report['tabs'].append({'route': slug, 'tab': name, 'status': 'PASS'})
                except Exception as exc:
                    report['tabs'].append({'route': slug, 'tab': name, 'status': 'FAIL', 'reason': str(exc)[:300]})
        pattern = '**/api/v1/sports/odds-intelligence/observations*'
        held = []
        page.route(pattern, lambda route: held.append(route))
        page.goto(BASE + '/sports/markets', wait_until='domcontentloaded')
        page.get_by_text('Loading price evidence…', exact=True).wait_for()
        report['states'].append({'state': 'LOADING', 'status': 'PASS'})
        page.unroute(pattern)
        for route in held: route.continue_()
        page.locator('.odds-evidence-panel table').wait_for()
        page.route(pattern, lambda route: route.abort('failed'))
        page.reload(wait_until='domcontentloaded')
        page.locator('.odds-evidence-panel [role="alert"]').wait_for()
        report['states'].append({'state': 'NETWORK_FAILURE', 'status': 'PASS'})
        browser.close()
    output = ROOT / 'artifacts/remediation/ui-interactions.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'tabs': len(report['tabs']), 'failures': [row for row in report['tabs'] if row['status'] != 'PASS'], 'states': report['states'], 'javascript_errors': report['javascript_errors']}))
    assert report['tabs'] and all(row['status'] == 'PASS' for row in report['tabs']) and not report['javascript_errors']


if __name__ == '__main__': main()
