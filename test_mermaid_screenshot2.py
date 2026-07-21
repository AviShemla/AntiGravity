from playwright.sync_api import sync_playwright
import os

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Start local server or just load index.html locally if it works
        # Actually it's easier to run a simple HTTP server in background and hit localhost
        import subprocess
        import time
        server = subprocess.Popen(["python", "server.py"], cwd="c:/Users/AviShemla/AntiGravity")
        time.sleep(3) # Wait for uvicorn to start
        
        try:
            page.goto('http://127.0.0.1:80')
            page.wait_for_selector('button:has-text("Architecture Blueprint")')
            
            # Click the blueprint tab
            page.click('button:has-text("Architecture Blueprint")')
            
            # Wait 5 seconds for rendering
            time.sleep(5)
            
            # Check console logs
            page.on("console", lambda msg: print(f"Browser console: {msg.text}"))
            
            # Take screenshot of the iframe specifically, or the whole page
            page.screenshot(path="mermaid_live_screenshot.png")
            print("Screenshot saved to mermaid_live_screenshot.png")
            
        finally:
            server.terminate()
            browser.close()

run()
