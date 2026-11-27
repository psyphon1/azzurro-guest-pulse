"""THROWAWAY SPIKE: find how to open the reviews panel and what pagination looks like."""
import json
from playwright.sync_api import sync_playwright

URL = "https://www.booking.com/hotel/au/olympic-paddington.html"
calls = []

def on_response(resp):
    req = resp.request
    if "graphql" in resp.url and req.method == "POST" and "ReviewList" in (req.post_data or ""):
        try:
            d = resp.json()
            cards = d["data"]["reviewListFrontend"]["reviewCard"]
            body = json.loads(req.post_data)
            calls.append((resp.status, len(cards), body.get("variables", {}).get("skip"), body.get("variables", {}).get("sorter")))
            if len(calls) == 1:
                json.dump(d, open("data/raw/spike_reviewlist.json", "w"))
        except Exception as e:
            calls.append((resp.status, "unreadable", repr(e)[:80], None))

with sync_playwright() as p:
    b = p.chromium.launch(headless=True)
    page = b.new_context(locale="en-GB", timezone_id="Australia/Sydney").new_page()
    page.on("response", on_response)
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)
    print("title:", page.title()[:50])
    # list candidate controls mentioning reviews
    for sel in ["[data-testid='fr-read-all-reviews']", "text=/read all reviews/i", "text=/see all reviews/i", "[data-testid*='review']"]:
        n = page.locator(sel).count()
        print(f"selector {sel!r}: {n} match(es)")
    btn = page.locator("[data-testid='fr-read-all-reviews']")
    if btn.count() == 0:
        btn = page.locator("text=/read all reviews/i")
    if btn.count():
        btn.first.scroll_into_view_if_needed()
        btn.first.click()
        page.wait_for_timeout(5000)
    print("ReviewList calls after opening panel:", calls)
    b.close()
