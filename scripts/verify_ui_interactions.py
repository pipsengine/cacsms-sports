"""Read-only tab interactions plus real request loading/network-failure states."""
import asyncio
import json
import os
import re
from pathlib import Path
from playwright.async_api import async_playwright, Error

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv('CACSMS_UI_URL', 'http://127.0.0.1:5173')
TABS = ','.join('.' + name + ' button' for name in ('dmr-tabs','af-tabs','bp-tabs','diag-tabs','lsi-tabs','mr-tabs','mgi-tabs','pa-tabs','dataset-tabs'))


async def main():
    navigation = (ROOT / 'apps/web/src/navigation.ts').read_text(encoding='utf-8').split('} as const')[0]
    targets = re.findall(r"\['([^']+)','([^']+)'\]", navigation)
    report = {'tabs': [], 'javascript_errors': [], 'states': []}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={'width': 1440, 'height': 1000})
        page.set_default_timeout(20000)
        await page.emulate_media(reduced_motion='reduce')
        page.on('pageerror', lambda error: report['javascript_errors'].append(str(error)))
        for _, slug in targets:
            await page.goto(BASE + '/sports/' + slug, wait_until='domcontentloaded')
            await page.locator('main.content').wait_for()
            await page.wait_for_timeout(350)
            names = await page.locator(TABS).all_text_contents()
            for name in names:
                button = page.locator(TABS).filter(has_text=re.compile('^' + re.escape(name) + '$')).first
                if not await button.is_visible() or not await button.is_enabled(): continue
                try:
                    await button.click()
                    await page.wait_for_timeout(150)
                    assert await page.locator('main.content').is_visible()
                    report['tabs'].append({'route': slug, 'tab': name, 'status': 'PASS'})
                except Exception as exc:
                    report['tabs'].append({'route': slug, 'tab': name, 'status': 'FAIL', 'reason': str(exc)[:300]})
        pattern = '**/api/v1/sports/odds-intelligence/observations*'
        release = asyncio.Event()
        async def hold(route):
            await release.wait()
            try:
                await route.continue_()
            except Error as exc:
                if 'already handled' not in str(exc): raise
        await page.route(pattern, hold)
        await page.goto(BASE + '/sports/markets', wait_until='domcontentloaded')
        await page.get_by_text(re.compile(r'^Loading price evidence')).wait_for()
        report['states'].append({'state': 'LOADING', 'status': 'PASS'})
        release.set()
        await page.locator('.odds-evidence-panel table').wait_for()
        await page.unroute_all(behavior='wait')
        async def fail(route): await route.abort('failed')
        await page.route(pattern, fail)
        await page.reload(wait_until='domcontentloaded')
        await page.locator('.odds-evidence-panel [role="alert"]').wait_for()
        report['states'].append({'state': 'NETWORK_FAILURE', 'status': 'PASS'})
        await page.unroute_all(behavior='wait')
        await page.goto('about:blank', wait_until='domcontentloaded')
        await browser.close()
    output = ROOT / 'artifacts/remediation/ui-interactions.json'
    output.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'tabs': len(report['tabs']), 'failures': [row for row in report['tabs'] if row['status'] != 'PASS'], 'states': report['states'], 'javascript_errors': report['javascript_errors']}))
    assert report['tabs'] and all(row['status'] == 'PASS' for row in report['tabs']) and not report['javascript_errors']


if __name__ == '__main__': asyncio.run(main())
