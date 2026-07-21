from playwright.sync_api import sync_playwright
import subprocess
import time
import os

def run():
    print("Starting local HTTP server...")
    server = subprocess.Popen(["python", "-m", "http.server", "8000"], cwd="c:/Users/AviShemla/AntiGravity/frontend")
    time.sleep(2)
    
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            # Catch all console messages
            page.on("console", lambda msg: print(f"BROWSER CONSOLE: {msg.text}"))
            page.on("pageerror", lambda err: print(f"BROWSER ERROR: {err}"))
            
            print("Navigating to index.html...")
            page.goto('http://127.0.0.1:8000/index.html')
            
            print("Waiting for Architecture Blueprint button...")
            page.wait_for_selector('button:has-text("Architecture Blueprint")')
            
            print("Clicking Architecture Blueprint tab...")
            page.click('button:has-text("Architecture Blueprint")')
            
            print("Waiting 5 seconds for rendering...")
            time.sleep(5)
            
            print("Taking screenshot...")
            page.screenshot(path="c:/Users/AviShemla/AntiGravity/mermaid_test_screenshot.png")
            
            # Let's also check the iframe's content
            frames = page.frames
            for frame in frames:
                if "Architecture_Map" in frame.url:
                    print("Found Architecture iframe!")
                    # Check if SVG exists
                    svg_count = frame.locator("svg").count()
                    print(f"SVG count inside iframe: {svg_count}")
                    # Evaluate bounding box
                    if svg_count > 0:
                        box = frame.locator("svg").first.bounding_box()
                        print(f"SVG bounding box: {box}")
                    
            browser.close()
    finally:
        server.terminate()
        print("Done.")

if __name__ == "__main__":
    run()
