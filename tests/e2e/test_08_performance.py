"""About 6,000 reviews over a year: is the page still quick for a manager?"""
import time

from tests.e2e.harness import choose, feed_total, no_traceback, search, settle, wait_for_app

LOAD_BUDGET_S = 20
ACTION_BUDGET_S = 12


def test_first_load_is_reasonably_fast_and_clean(playwright_browser, big_server):
    ctx = playwright_browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    from tests.e2e.harness import Monitor
    mon = Monitor(page)
    start = time.time()
    page.goto(big_server.url, timeout=60000)
    wait_for_app(page, 60000)
    page.get_by_role("heading", name="Review feed").wait_for()
    elapsed = time.time() - start
    ctx.close()
    assert elapsed < LOAD_BUDGET_S, f"first load took {elapsed:.1f}s"
    mon.assert_clean()


def test_switching_to_all_time_on_a_year_of_data_stays_responsive(open_app, big_server):
    page, mon = open_app(big_server)
    start = time.time()
    choose(page, "Time period", "All time")
    assert time.time() - start < ACTION_BUDGET_S
    assert feed_total(page) > 1000
    mon.assert_clean()


def test_searching_a_big_feed_stays_responsive(open_app, big_server):
    page, _ = open_app(big_server)
    choose(page, "Time period", "All time")
    start = time.time()
    search(page, "noisy")
    assert time.time() - start < ACTION_BUDGET_S
    no_traceback(page)


def test_paging_a_big_feed_stays_responsive(open_app, big_server):
    page, _ = open_app(big_server)
    choose(page, "Time period", "All time")
    start = time.time()
    for _ in range(5):
        page.get_by_role("button", name="Next page").click()
        settle(page)
    assert (time.time() - start) / 5 < 6
    no_traceback(page)


def test_the_page_does_not_grow_without_bound(open_app, big_server):
    page, _ = open_app(big_server)
    choose(page, "Time period", "All time")
    assert page.locator(".az-review").count() <= 10               # only one page of reviews is ever drawn
    assert page.evaluate("document.querySelectorAll('*').length") < 8000
