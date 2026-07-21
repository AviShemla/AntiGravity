from playwright.sync_api import sync_playwright
import subprocess
import time

def run():
    print("Starting local server...")
    server = subprocess.Popen(["C:/Users/AviShemla/AppData/Local/Python/pythoncore-3.14-64/python.exe", "-m", "http.server", "8000"], cwd="c:/Users/AviShemla/AntiGravity/frontend")
    time.sleep(2)
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            page.goto('http://127.0.0.1:8000/index.html')
            page.wait_for_selector('button:has-text("Architecture Blueprint")')
            page.click('button:has-text("Architecture Blueprint")')
            
            time.sleep(4)
            
            page.screenshot(path="c:/Users/AviShemla/AntiGravity/final_mermaid_screenshot.png")
            print("Screenshot saved to final_mermaid_screenshot.png")
            
            browser.close()
    finally:
        server.terminate()
        print("Done.")

if __name__ == "__main__":
    run()
