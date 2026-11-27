"""Live fetching through a real, visible browser window.

Why a browser: Booking.com sits behind AWS WAF bot protection and the review call is tied to a
browser session. A normal browser passes the check on its own. We do not forge tokens or disguise
automation. Headless mode is refused by the site (HTTP 400 "Request not supported"), so a visible
window is required. See docs/adr/001-collection-method.md.

This module talks to the live site, so it is covered by a manual smoke test, not unit tests.
Everything it feeds (parse, store, collector) is unit tested.
"""
import random
import time
from typing import Iterator

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from scraper.errors import BlockedError, FetchError
from scraper.models import ParsedPage
from scraper.parse import parse_page

CHALLENGE_WAIT_S = 30
PAGE_DELAY_S = (2.0, 5.0)  # polite, randomised pause between pages
MAX_PAGES = 200  # hard safety stop

READ_ALL = "[data-testid='fr-read-all-reviews']"
SORTER = "[data-testid='reviews-sorter-component']"
NEXT_PAGE = "button[aria-label='Next page']"


def _is_review_list(resp) -> bool:
    req = resp.request
    return "graphql" in resp.url and req.method == "POST" and "ReviewList" in (req.post_data or "")


def _read(resp, slug: str) -> ParsedPage:
    try:
        payload = resp.json()
    except Exception as exc:  # not JSON at all: usually an HTML block page
        raise BlockedError(f"ReviewList did not return JSON (HTTP {resp.status})") from exc
    front = ((payload.get("data") or {}).get("reviewListFrontend")) or {}
    if front.get("statusCode") in (400, 403, 429):
        raise BlockedError(f"HTTP {front['statusCode']} {front.get('message')}")
    return parse_page(payload, slug)


def fetch_pages(url: str, slug: str, headless: bool = False) -> Iterator[ParsedPage]:
    """Yield review pages newest-first. Lazy: the caller can stop early and we stop clicking."""
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
            try:
                page = browser.new_context(locale="en-GB", timezone_id="Australia/Sydney").new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                _wait_for_challenge(page)

                page.locator(READ_ALL).first.scroll_into_view_if_needed()
                with page.expect_response(_is_review_list, timeout=30_000):
                    page.locator(READ_ALL).first.click()
                page.wait_for_selector(SORTER, timeout=15_000)

                with page.expect_response(_is_review_list, timeout=30_000) as info:
                    page.select_option(SORTER, "NEWEST_FIRST")
                yield _read(info.value, slug)

                for _ in range(MAX_PAGES):
                    nxt = page.locator(NEXT_PAGE)
                    if nxt.count() == 0 or nxt.first.is_disabled():
                        return
                    time.sleep(random.uniform(*PAGE_DELAY_S))
                    with page.expect_response(_is_review_list, timeout=30_000) as info:
                        nxt.first.click()
                    yield _read(info.value, slug)
            finally:
                browser.close()
    except PlaywrightTimeout as exc:
        raise FetchError(f"Timed out waiting for the page: {str(exc)[:120]}") from exc
    except PlaywrightError as exc:
        raise FetchError(f"Browser error: {str(exc)[:120]}") from exc


def _wait_for_challenge(page) -> None:
    """The WAF interstitial resolves itself in a few seconds in a normal browser. Wait for it, politely."""
    deadline = time.time() + CHALLENGE_WAIT_S
    while time.time() < deadline:
        if page.locator(READ_ALL).count() > 0:
            return
        page.wait_for_timeout(1000)
    raise BlockedError("Bot check did not clear and the reviews section never appeared")
