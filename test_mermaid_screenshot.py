from playwright.sync_api import sync_playwright
import os

html_path = f"file://{os.path.abspath('frontend/Architecture_Map.html')}"

def run():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(html_path, wait_until="networkidle")
        page.wait_for_timeout(3000)
        page.screenshot(path="screenshot.png", full_page=True)
        browser.close()

if __name__ == "__main__":
    run()
