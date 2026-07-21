from playwright.sync_api import sync_playwright
import os
import subprocess
import time

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        server = subprocess.Popen(["C:/Users/AviShemla/AppData/Local/Python/pythoncore-3.14-64/python.exe", "-m", "uvicorn", "server:app", "--host", "127.0.0.1", "--port", "8000"], cwd="c:/Users/AviShemla/AntiGravity")
        time.sleep(4)
        
        try:
            page.goto('http://127.0.0.1:8000')
            page.wait_for_selector('button:has-text("Architecture Blueprint")')
            
            page.click('button:has-text("Architecture Blueprint")')
            time.sleep(5)
            
            page.screenshot(path="mermaid_live_screenshot.png")
            print("Screenshot saved to mermaid_live_screenshot.png")
            
        finally:
            server.terminate()
            browser.close()

run()
