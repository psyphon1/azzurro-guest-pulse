"""THROWAWAY SPIKE: does the WAF challenge clear on its own if we simply wait?"""
import sys
from playwright.sync_api import sync_playwright

URL = "https://www.booking.com/hotel/au/olympic-paddington.html"
headless = "--headed" not in sys.argv

with sync_playwright() as p:
    browser = p.chromium.launch(headless=headless)
    ctx = browser.new_context(locale="en-GB", timezone_id="Australia/Sydney")
    page = ctx.new_page()
    r = page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    print("headless:", headless, "| first status:", r.status)
    for i in range(6):
        page.wait_for_timeout(5000)
        title = page.title()
        has_reviews = "review" in page.content().lower() and "hotel" in title.lower()
        print(f"t+{(i+1)*5}s title={title[:60]!r} url_ok={'olympic' in page.url} looks_like_hotel_page={has_reviews}")
        if has_reviews:
            break
    browser.close()
