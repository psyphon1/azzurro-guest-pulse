"""Fresh data shows up, two people do not disturb each other, and hammering the buttons does not break anything."""
from datetime import date, datetime, timedelta, timezone

from scraper.models import Review
from scraper.store import ReviewStore
from tests.e2e import dbs
from tests.e2e.harness import (AppServer, Monitor, cards, choose, feed_total, no_traceback, only_hotels, settle, sidebar,
                               wait_for_app)


def test_a_review_added_to_the_database_appears_after_a_refresh(playwright_browser, e2e_folder, request):
    folder = e2e_folder / "cache-test"
    folder.mkdir()
    path = dbs.main_db(folder)
    server = AppServer(str(path))
    request.addfinalizer(server.stop)
    ctx = playwright_browser.new_context()
    page = ctx.new_page()
    page.goto(server.url); wait_for_app(page)
    choose(page, "Time period", "All time")
    before = feed_total(page)

    store = ReviewStore(str(path), clock=lambda: datetime(2026, 11, 28, tzinfo=timezone.utc))      # the scraper adds a review
    store.upsert_reviews([Review(review_key="fresh-review-1", property="olympic-paddington", rating=3.0,
                                 review_date=date(2026, 11, 27), language="en", disliked="Brand new complaint about the lift")])
    store.close()

    page.reload(); wait_for_app(page)
    choose(page, "Time period", "All time")
    assert feed_total(page) == before + 1, "the dashboard served stale data after the database changed"
    ctx.close()


def test_two_people_at_once_do_not_affect_each_others_filters(open_app, main_server):
    page_a, _ = open_app(main_server)
    page_b, _ = open_app(main_server)
    only_hotels(page_a, ["Potts Point"])
    assert sidebar(page_a).locator("[data-tag]").all_inner_texts() == ["Potts Point"]
    assert len(sidebar(page_b).locator("[data-tag]").all_inner_texts()) == 4       # B is untouched


def test_hammering_the_next_button_leaves_a_consistent_page(open_app, main_server):
    page, mon = open_app(main_server)
    choose(page, "Time period", "All time")
    nxt = page.get_by_role("button", name="Next page")
    for _ in range(8):
        if nxt.is_enabled():
            nxt.click(no_wait_after=True)
    settle(page)
    no_traceback(page)
    assert 0 < cards(page).count() <= 10
    mon.assert_clean()


def test_rapid_filter_changes_never_leave_the_page_stuck(open_app, main_server):
    page, mon = open_app(main_server)
    for preset in ("Last week", "Last 4 weeks", "All time", "Last 12 weeks", "Latest full week"):
        page.get_by_role("combobox", name="Time period").click()
        page.get_by_role("option", name=preset, exact=True).click()
    settle(page)
    no_traceback(page)
    mon.assert_clean()
