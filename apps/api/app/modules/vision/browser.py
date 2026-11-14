"""Authorized browser capture. Capture is evidence, not computer-vision interpretation."""
import asyncio,os
from pathlib import Path
from urllib.parse import urlsplit
from app.modules.vision.security import validate_destination
from app.modules.vision.extraction import screenshot_record

async def capture(url:str,fixture_id:str,approved_hosts:list[str],evidence_root:str):
    validate_destination(url,approved_hosts)
    try:from playwright.async_api import async_playwright
    except ImportError as exc:raise RuntimeError('Install optional playwright dependency and Chromium') from exc
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(headless=True)
        try:
            context=await browser.new_context(accept_downloads=False,service_workers='block')
            async def restrict(route):
                target=route.request.url
                try:validate_destination(target,approved_hosts)
                except (ValueError,PermissionError, OSError):await route.abort();return
                await route.continue_()
            await context.route('**/*',restrict)
            page=await context.new_page()
            await page.goto(url,wait_until='domcontentloaded',timeout=20000)
            image=await page.screenshot(full_page=False,timeout=10000)
            record=screenshot_record(image,url,fixture_id)
            root=Path(evidence_root).resolve();root.mkdir(parents=True,exist_ok=True)
            file=root/(record['sha256']+'.png');file.write_bytes(image)
            record['storage_key']=file.name
            await context.close()
            return record
        finally:await browser.close()
