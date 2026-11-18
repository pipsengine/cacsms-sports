"""Authorized browser capture. Capture is evidence, not computer-vision interpretation."""
import asyncio,os,time
from pathlib import Path
from urllib.parse import urljoin
from app.modules.vision.security import validate_destination
from app.modules.vision.extraction import screenshot_record

REDIRECT_STATUSES={301,302,303,307,308}
GUARD_ERRORS=(ValueError,PermissionError,OSError)


async def _permitted(url,approved_hosts):
    """Run the (DNS-resolving, blocking) destination check off the event loop; True when the URL may be requested."""
    try:await asyncio.to_thread(validate_destination,url,approved_hosts);return True
    except GUARD_ERRORS:return False


async def guard_route(route,approved_hosts,subresource_hosts=None):
    """Every request, and every redirect hop, must pass the destination policy.

    Playwright does not invoke route handlers for redirect hops, so the request is fetched here without following
    redirects; a 3xx is only handed to the browser after its Location passes the same check (the browser's follow-up
    request is then routed through this guard again)."""
    target=route.request.url
    navigation=getattr(route.request,'is_navigation_request',lambda:True)()
    hosts=approved_hosts if navigation else [*approved_hosts,*(subresource_hosts or [])]
    if not await _permitted(target,hosts):await route.abort('blockedbyclient');return
    try:response=await route.fetch(max_redirects=0)
    except Exception:await route.abort('failed');return
    if response.status in REDIRECT_STATUSES:
        location=urljoin(target,response.headers.get('location') or '')
        if not location or not await _permitted(location,hosts):
            await response.dispose();await route.abort('blockedbyclient');return
    await route.fulfill(response=response)


async def capture(url:str,fixture_id:str,approved_hosts:list[str],evidence_root:str):
    validate_destination(url,approved_hosts)
    try:from playwright.async_api import async_playwright
    except ImportError as exc:raise RuntimeError('Install optional playwright dependency and Chromium') from exc
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(headless=True)
        try:
            context=await browser.new_context(accept_downloads=False,service_workers='block')
            subresources=[host.strip() for host in os.getenv('SPORTS_BROWSER_SUBRESOURCE_HOSTS','').split(',') if host.strip()]
            await context.route('**/*',lambda route:guard_route(route,approved_hosts,subresources))
            page=await context.new_page()
            started=time.monotonic()
            response=await page.goto(url,wait_until='domcontentloaded',timeout=20000)
            duration_ms=round((time.monotonic()-started)*1000)
            # Defence in depth: never record evidence from a page that ended up outside the approved hosts.
            validate_destination(page.url,approved_hosts)
            image=await page.screenshot(full_page=False,timeout=10000)
            record=screenshot_record(image,page.url,fixture_id)
            root=Path(evidence_root).resolve();root.mkdir(parents=True,exist_ok=True)
            file=root/(record['sha256']+'.png');file.write_bytes(image)
            record['storage_key']=file.name
            status=response.status if response is not None else None
            error='NAVIGATION_NO_RESPONSE' if status is None else f'HTTP_{status}' if not 200<=status<300 else None
            record.update(http_status=status,page_title=await page.title(),navigation_duration_ms=duration_ms,
                          capture_status='FAILED' if error else 'CAPTURED',error=error)
            if error:record['vision_status']='NOT_PERFORMED'
            await context.close()
            return record
        finally:await browser.close()
