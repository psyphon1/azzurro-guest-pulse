"""THROWAWAY SPIKE: print the shape of each ReviewList request/response (no personal text)."""
import json
from playwright.sync_api import sync_playwright

URL = "https://www.booking.com/hotel/au/olympic-paddington.html"
rows = []

def on_response(resp):
    req = resp.request
    if "graphql" in resp.url and req.method == "POST" and "ReviewList" in (req.post_data or ""):
        body = json.loads(req.post_data)
        v = body.get("variables", {})
        try:
            d = resp.json()
        except Exception:
            d = {}
        rf = ((d.get("data") or {}).get("reviewListFrontend")) or {}
        rows.append({
            "status": resp.status,
            "top_keys": list(d.keys()),
            "errors": str(d.get("errors"))[:200] if d.get("errors") else None,
            "frontend_keys": sorted(rf.keys())[:12],
            "msg": str(rf.get("message"))[:200], "code": rf.get("statusCode"),
            "input_keys": sorted((v.get("input") or {}).keys()),
            "cards": len(rf.get("reviewCard") or []),
            "var_keys": sorted(v.keys()),
            "skip": v.get("skip"), "limit": v.get("limit"), "sorter": v.get("sorter"),
            "has_hash": "sha256Hash" in json.dumps(body.get("extensions", {})),
        })

with sync_playwright() as p:
    b = p.chromium.launch(headless=False)
    page = b.new_context(locale="en-GB", timezone_id="Australia/Sydney").new_page()
    page.on("response", on_response)
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)
    page.locator("[data-testid='fr-read-all-reviews']").first.click()
    page.wait_for_timeout(6000)
    for r in rows:
        print(json.dumps(r))
    # What does the dialog look like now?
    print("dialogs:", page.locator("[role='dialog']").count(), "| review cards in DOM:", page.locator("[data-testid='review-card']").count())
    print("pagination-ish:", [page.locator(s).count() for s in ["[data-testid='review-pagination']", "[aria-label*='page' i]", "button:has-text('Next')"]])
    b.close()
