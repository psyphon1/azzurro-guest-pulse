"""THROWAWAY SPIKE: what does Central Sydney's review section say, and when does the button appear?"""
import re, time
from playwright.sync_api import sync_playwright

URL = "https://www.booking.com/hotel/au/venus-surry-hills.html"
with sync_playwright() as p:
    b = p.chromium.launch(headless=False)
    page = b.new_context(locale="en-GB", timezone_id="Australia/Sydney").new_page()
    t0 = time.time(); page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    seen_at = None
    while time.time() - t0 < 25:
        if page.locator("[data-testid='fr-read-all-reviews']").count() and seen_at is None:
            seen_at = round(time.time() - t0, 1)
        page.wait_for_timeout(500)
    print("READ_ALL first seen at (s):", seen_at)
    for tid in ("reviews-block-title", "review-score-component", "review-score-read-all", "fr-read-all-reviews", "reviews-block-availability"):
        loc = page.locator(f"[data-testid='{tid}']")
        print(tid, "->", [t[:160].replace("\n", " | ") for t in loc.all_inner_texts()][:2])
    body = page.inner_text("body")
    for m in re.finditer(r"(?i)no reviews yet|be the first|not enough reviews|reviews? \(\d+\)|\d+ reviews?", body):
        s = max(0, m.start() - 60); print("  ctx:", body[s:m.end() + 60].replace("\n", " | "))
        break
    print("all 'N reviews' mentions:", re.findall(r"(?i)\d[\d,]* reviews?", body)[:6])
    b.close()
