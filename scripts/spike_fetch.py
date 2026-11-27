"""THROWAWAY SPIKE (not test-driven, not product code).
Question: does a real browser at low volume get ReviewList responses from the property page?
"""
import json
import sys

from playwright.sync_api import sync_playwright

URL = "https://www.booking.com/hotel/au/olympic-paddington.html"
seen = []


def on_response(resp):
    req = resp.request
    if "graphql" in resp.url and req.method == "POST":
        body = req.post_data or ""
        if "ReviewList" in body:
            seen.append(resp)


with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    ctx = browser.new_context(locale="en-GB", timezone_id="Australia/Sydney")
    page = ctx.new_page()
    page.on("response", on_response)
    r = page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    print("page status:", r.status, "| title:", page.title())
    page.wait_for_timeout(6000)
    print("ReviewList responses on initial load:", len(seen))
    html = page.content()
    for marker in ("awswaf", "captcha", "Access Denied", "challenge"):
        print(f"  marker {marker!r} in html:", marker.lower() in html.lower())
    for resp in seen:
        try:
            data = resp.json()
            cards = data["data"]["reviewListFrontend"]["reviewCard"]
            print("  ReviewList status", resp.status, "cards", len(cards))
            with open("data/raw/spike_reviewlist.json", "w") as f:
                json.dump(data, f)
        except Exception as e:
            print("  could not read response:", resp.status, repr(e)[:150])
    browser.close()
