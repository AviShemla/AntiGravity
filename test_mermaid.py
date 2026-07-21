from playwright.sync_api import sync_playwright
import os

html_path = f"file://{os.path.abspath('frontend/Architecture_Map.html')}"

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Listen for console events
        page.on("console", lambda msg: print(f"CONSOLE {msg.type}: {msg.text}"))
        page.on("pageerror", lambda err: print(f"PAGE ERROR: {err}"))
        
        print(f"Loading {html_path}...")
        page.goto(html_path, wait_until="networkidle")
        
        print("Waiting 2 seconds to allow Mermaid to render...")
        page.wait_for_timeout(2000)
        
        # Check if svg exists
        svg_count = page.locator("svg").count()
        print(f"Number of SVG elements found: {svg_count}")
        
        browser.close()

if __name__ == "__main__":
    run()
