"""Live fetching through a real, visible browser window.

Why a browser: Booking.com sits behind AWS WAF bot protection and the review call is tied to a
browser session. A normal browser passes the check on its own. We do not forge tokens or disguise
automation. Headless mode is refused by the site (HTTP 400 "Request not supported"), so a visible
window is required. See docs/adr/001-collection-method.md.

This module talks to the live site, so it is covered by a manual smoke test, not unit tests.
Everything it feeds (parse, store, collector) is unit tested.
"""
import json
import random
import re
import time
from typing import Iterator
from urllib.parse import urlsplit

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from scraper.config import HARD_MAX_PAGES
from scraper.errors import BlockedError, EndedEarlyError, FetchError
from scraper.models import ParsedPage, clean_text
from scraper.pagination import next_step
from scraper.parse import parse_page

CHALLENGE_WAIT_S = 30
PAGE_DELAY_S = (2.0, 5.0)  # polite, randomised pause between pages
MAX_PAGES = HARD_MAX_PAGES  # absolute safety valve only; the real, recorded limit is --max-pages in the collector
MAX_RESPONSE_BYTES = 5 * 1024 * 1024  # a real ReviewList page is ~30 KB; anything near this is hostile or broken

BOOKING_HOST = "www.booking.com"
_PROPERTY_URL = re.compile(r"https://www\.booking\.com/hotel/[a-z]{2}/[a-z0-9][a-z0-9-]{0,99}\.html")
# After navigation Booking may add a locale suffix (.en-gb) and tracking parameters, but never change host or section.
_FINAL_PATH = re.compile(r"/hotel/[a-z]{2}/[a-z0-9][a-z0-9-]{0,99}(?:\.[a-z]{2}(?:-[a-z]{2})?)?\.html")
_UNSAFE_URL_CHARS = re.compile(r"[\x00-\x20\x7f-\x9f\\]")


def is_allowed_property_url(url) -> bool:
    """The ONLY thing we will ever point the browser at: https://www.booking.com/hotel/<cc>/<slug>.html"""
    return isinstance(url, str) and len(url) <= 200 and _PROPERTY_URL.fullmatch(url) is not None


def is_allowed_final_url(url) -> bool:
    """Where the browser may be after navigation (open-redirect / SSRF guard). Query and fragment are allowed
    (Booking appends tracking parameters); host, scheme, port, credentials and path section are not negotiable."""
    if not isinstance(url, str) or len(url) > 2048 or _UNSAFE_URL_CHARS.search(url):
        return False
    try:
        parts = urlsplit(url)
    except ValueError:
        return False
    return (parts.scheme == "https" and parts.netloc == BOOKING_HOST
            and _FINAL_PATH.fullmatch(parts.path) is not None)


def _check_page_url(page) -> None:
    if not is_allowed_final_url(page.url):
        raise BlockedError(f"Navigation ended on an unexpected address (redirect away from booking.com property "
                           f"page): {clean_text(str(page.url), 80)!r}. Stopped before reading anything.")


# Off-screen window position for background collection: the browser is a normal, visible (headed) Chromium,
# exactly what Booking.com already accepts; it is only placed where it does not cover the user's screen.
_OFF_SCREEN = ["--window-position=-32000,-32000", "--window-size=1280,900"]


def launch_options(headless: bool, hidden: bool = False) -> dict:
    """Plain launch: no profile directory, no download folder, no sandbox-disabling flags.
    `hidden` keeps the (headed) window off-screen for runs started from the dashboard."""
    if hidden and not headless:
        return {"headless": False, "args": list(_OFF_SCREEN)}
    return {"headless": headless}


def context_options() -> dict:
    """A fresh, in-memory context for every run: no persistent profile (so no cookies or tokens reach the disk),
    downloads off, no permissions (camera, location, notifications ...), no service workers, TLS errors are fatal."""
    return {
        "locale": "en-GB",
        "timezone_id": "Australia/Sydney",
        "accept_downloads": False,
        "permissions": [],
        "service_workers": "block",
        "ignore_https_errors": False,
        "java_script_enabled": True,
    }

READ_ALL = "[data-testid='fr-read-all-reviews']"
SORTER = "[data-testid='reviews-sorter-component']"
NEXT_PAGE = "button[aria-label='Next page']"


def _is_review_list(resp) -> bool:
    """Only trust a ReviewList answer that really came from https://www.booking.com (a third-party frame or an
    injected request that merely has 'graphql' in its URL must not be able to feed us data)."""
    try:
        parts = urlsplit(resp.url)
    except ValueError:
        return False
    if parts.scheme != "https" or parts.netloc != BOOKING_HOST or "graphql" not in parts.path:
        return False
    req = resp.request
    return req.method == "POST" and "ReviewList" in (req.post_data or "")


def _reject_constant(name):
    raise ValueError(f"{name} is not valid JSON")


def _read(resp, slug: str) -> ParsedPage:
    body = resp.body()
    if len(body) > MAX_RESPONSE_BYTES:
        raise FetchError(f"ReviewList response too large ({len(body)} bytes, limit {MAX_RESPONSE_BYTES}); refused")
    try:
        payload = json.loads(body, parse_constant=_reject_constant)
    except (ValueError, RecursionError) as exc:  # not JSON, NaN/Infinity, absurdly nested: usually an HTML block page
        raise BlockedError(f"ReviewList did not return usable JSON (HTTP {resp.status})") from exc
    data = payload.get("data") if isinstance(payload, dict) else None
    front = data.get("reviewListFrontend") if isinstance(data, dict) else None
    if isinstance(front, dict) and front.get("statusCode") in (400, 403, 429):
        raise BlockedError(f"HTTP {front['statusCode']} {clean_text(str(front.get('message')), 100)}")
    return parse_page(payload, slug)


RETRY_WAIT_MS = 5000   # how long to wait before looking again when 'Next page' has vanished unexpectedly


def walk_pages(first: ParsedPage, next_available, advance, wait, delay) -> Iterator[ParsedPage]:
    """Yield `first`, then keep advancing page by page. The browser is passed in as plain callables so this loop
    is unit tested without Playwright.

    A missing 'Next page' button only ends the walk when scraper.pagination.next_step says it really is the end.
    If it vanishes while Booking.com still reports far more reviews, wait and look again; if it never returns,
    raise EndedEarlyError (the pages already yielded were saved by the caller)."""
    last, cards_seen, pages, retries = first, len(first.reviews) + len(first.rejected), 1, 0
    yield first
    while True:
        decision = next_step(last_page_size=len(last.reviews) + len(last.rejected), collected=cards_seen,
                             reported_total=last.reported_total, next_available=next_available(), retries_used=retries)
        if decision == "end":
            return
        if decision == "ended_early":
            raise EndedEarlyError(
                f"The list stopped after page {pages} with {cards_seen} of {last.reported_total} reviews. "
                "Booking.com most likely throttled us (or limits how far back the list goes). "
                "Pages already saved were kept; try again later.")
        if decision == "retry":
            retries += 1
            wait()
            continue
        if pages >= MAX_PAGES:
            raise FetchError(f"Reached the {MAX_PAGES}-page ceiling while more pages were still offered")
        retries = 0
        delay()
        last = advance()
        pages += 1
        cards_seen += len(last.reviews) + len(last.rejected)
        yield last


def fetch_pages(url: str, slug: str, headless: bool = False, hidden: bool = False) -> Iterator[ParsedPage]:
    """Yield review pages newest-first. Lazy: the caller can stop early and we stop clicking."""
    if not is_allowed_property_url(url):
        raise FetchError(f"Refused to open {clean_text(str(url), 80)!r}: not on the allow-list "
                         "(https://www.booking.com/hotel/<cc>/<slug>.html)")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(**launch_options(headless, hidden))
            try:
                page = browser.new_context(**context_options()).new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=60_000)
                _check_page_url(page)
                _wait_for_challenge(page)
                _check_page_url(page)

                _open_reviews_panel(page)
                _check_page_url(page)

                with page.expect_response(_is_review_list, timeout=30_000) as info:
                    page.select_option(SORTER, "NEWEST_FIRST")
                if page.locator(SORTER).input_value() != "NEWEST_FIRST":
                    raise FetchError("Could not switch the reviews to 'Newest first'; stopped rather than read them in the wrong order")
                first = _read(info.value, slug)

                def next_available() -> bool:
                    nxt = page.locator(NEXT_PAGE)
                    return nxt.count() > 0 and not nxt.first.is_disabled()

                def advance() -> ParsedPage:
                    with page.expect_response(_is_review_list, timeout=30_000) as nxt_info:
                        page.locator(NEXT_PAGE).first.click()
                    _check_page_url(page)
                    return _read(nxt_info.value, slug)

                yield from walk_pages(first, next_available, advance,
                                      wait=lambda: page.wait_for_timeout(RETRY_WAIT_MS),
                                      delay=lambda: time.sleep(random.uniform(*PAGE_DELAY_S)))
            finally:
                browser.close()
    except PlaywrightTimeout as exc:
        raise FetchError(f"Timed out waiting for the page: {str(exc)[:120]}") from exc
    except PlaywrightError as exc:
        raise FetchError(f"Browser error: {str(exc)[:120]}") from exc


def _open_reviews_panel(page, attempts: int = 3) -> None:
    """Click 'Read all reviews'. The page re-renders after the bot check, so the button can be
    replaced under us. Click directly (Playwright re-finds the element) and retry a few times."""
    page.wait_for_load_state("load", timeout=30_000)
    page.wait_for_timeout(2000)  # let the page finish re-rendering
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            with page.expect_response(_is_review_list, timeout=20_000):
                page.locator(READ_ALL).first.click(timeout=15_000)
            page.wait_for_selector(SORTER, timeout=15_000)
            return
        except (PlaywrightTimeout, PlaywrightError) as exc:
            last_error = exc
            page.wait_for_timeout(2000)
    raise FetchError(f"Could not open the reviews panel after {attempts} tries: {str(last_error)[:120]}")


def _wait_for_challenge(page) -> None:
    """The WAF interstitial resolves itself in a few seconds in a normal browser. Wait for it, politely."""
    deadline = time.time() + CHALLENGE_WAIT_S
    while time.time() < deadline:
        if page.locator(READ_ALL).count() > 0:
            return
        page.wait_for_timeout(1000)
    raise BlockedError("Bot check did not clear and the reviews section never appeared")
