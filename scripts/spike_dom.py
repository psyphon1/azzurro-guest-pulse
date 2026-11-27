"""THROWAWAY SPIKE: describe pagination and sort controls in the reviews dialog."""
from playwright.sync_api import sync_playwright

URL = "https://www.booking.com/hotel/au/olympic-paddington.html"
with sync_playwright() as p:
    b = p.chromium.launch(headless=False)
    page = b.new_context(locale="en-GB", timezone_id="Australia/Sydney").new_page()
    page.goto(URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(7000)
    page.locator("[data-testid='fr-read-all-reviews']").first.click()
    page.wait_for_timeout(5000)
    dlg = page.locator("[role='dialog']").last
    print("page buttons:")
    for el in dlg.locator("[aria-label*='page' i]").all()[:16]:
        print("  ", el.evaluate("e => e.tagName + ' | ' + (e.getAttribute('aria-label')||'') + ' | ' + (e.getAttribute('aria-current')||'') + ' | ' + (e.getAttribute('data-testid')||'')"))
    print("selects:", dlg.locator("select").count())
    for el in dlg.locator("select").all():
        print("  select:", el.evaluate("e => (e.getAttribute('data-testid')||'') + ' | ' + (e.getAttribute('name')||'') + ' | ' + Array.from(e.options).map(o=>o.value).join(',')"))
    print("sort-ish buttons:", dlg.locator("text=/most relevant|newest first/i").count())
    b.close()
