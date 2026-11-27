"""THROWAWAY SPIKE: why is Central Sydney 'blocked'? One page load, print what the page contains."""
from playwright.sync_api import sync_playwright

URL = "https://www.booking.com/hotel/au/venus-surry-hills.html"
with sync_playwright() as p:
    b = p.chromium.launch(headless=False)
    page = b.new_context(locale="en-GB", timezone_id="Australia/Sydney").new_page()
    r = page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    print("first status:", r.status)
    for i in range(6):
        page.wait_for_timeout(5000)
        print(f"t+{(i+1)*5}s title={page.title()[:70]!r} url={page.url[:80]!r}")
    print("read-all testid present:", page.locator("[data-testid='fr-read-all-reviews']").count())
    print("text 'read all reviews':", page.locator("text=/read all reviews/i").count(), "| 'reviews' buttons:", page.locator("button:has-text('review')").count(), "| 'see all' :", page.locator("text=/see (all|guest) reviews|guest reviews/i").count())
    ids = page.evaluate("Array.from(document.querySelectorAll('[data-testid*=review i]')).map(e=>e.getAttribute('data-testid')).slice(0,15)")
    print("review-ish testids:", ids)
    html = page.content().lower()
    for marker in ("awswaf", "captcha", "access denied", "unusual traffic", "robot", "no reviews yet", "not yet reviewed", "be the first"):
        print(f"  marker {marker!r}:", marker in html)
    b.close()
