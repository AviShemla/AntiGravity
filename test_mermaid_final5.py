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
            
            print("Going to index.html...")
            # Wait until all JS is loaded
            page.goto('http://127.0.0.1:8000/index.html', wait_until='networkidle')
            
            print("Evaluating script to switch tab...")
            # Just click the last button directly in the DOM
            page.evaluate("""
                const buttons = document.querySelectorAll('.nav-button');
                buttons[buttons.length - 1].click();
            """)
            
            print("Waiting 5 seconds for rendering...")
            time.sleep(5)
            
            print("Taking screenshot...")
            page.screenshot(path="c:/Users/AviShemla/AntiGravity/final_mermaid_screenshot_5.png")
            print("Screenshot saved to final_mermaid_screenshot_5.png")
            
            browser.close()
    finally:
        server.terminate()
        print("Done.")

if __name__ == "__main__":
    run()
