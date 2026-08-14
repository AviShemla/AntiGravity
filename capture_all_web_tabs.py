import asyncio
import os
from playwright.async_api import async_playwright

ARTIFACT_DIR = r"C:\Users\AviShemla\.gemini\antigravity\brain\01e9aa77-80c5-489b-8bac-9eba71ae877f"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 900})
        
        print("Navigating to http://66.42.118.26...")
        await page.goto("http://66.42.118.26", wait_until="domcontentloaded", timeout=15000)
        
        print("Waiting for Tab 1 API data to populate...")
        try:
            await page.wait_for_function("document.getElementById('eq-stocks') && document.getElementById('eq-stocks').innerText !== '$0.00'", timeout=10000)
        except Exception as e:
            print(f"Wait timeout for eq-stocks: {e}")
            
        tabs = [
            ("live_tab_1_stocks", "stocks"),
            ("live_tab_2_etfs", "etfs"),
            ("live_tab_3_olympic", "olympic"),
            ("live_tab_4_prodshadow", "prodshadow"),
            ("live_tab_5_autopsy", "autopsy")
        ]
        
        for file_prefix, tab_id in tabs:
            print(f"Capturing tab: {tab_id}...")
            if tab_id != "stocks":
                await page.click(f"li[data-tab='{tab_id}']")
                await page.wait_for_timeout(3000)
            else:
                await page.wait_for_timeout(2000)
                
            out_path = os.path.join(ARTIFACT_DIR, f"{file_prefix}.png")
            await page.screenshot(path=out_path, full_page=True)
            print(f"Saved screenshot: {out_path}")
            
        await browser.close()

if __name__ == '__main__':
    asyncio.run(main())
