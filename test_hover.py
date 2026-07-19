import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={'width': 1280, 'height': 720})
        await page.goto('http://66.42.118.26/Architecture_Map.html')
        await page.wait_for_timeout(2000)
        
        # Find the node that has JSON API text
        element = await page.query_selector("g.node:has-text('JSON API')")
        if element:
            await element.hover()
            await page.wait_for_timeout(1000)
            await page.screenshot(path='C:/Users/AviShemla/AntiGravity/hover_test.png')
            print("Screenshot saved.")
        else:
            print("Element not found!")
            
        await browser.close()

asyncio.run(run())
