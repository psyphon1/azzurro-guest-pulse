import pytest

from scraper.collector import collect_property
from scraper.errors import BlockedError, FetchError
from scraper.models import ParsedPage, RejectedReview
from scraper.store import ReviewStore

SLUG = "olympic-paddington"


@pytest.fixture
def store():
    return ReviewStore(":memory:")


def page_of(reviews, total=None, rejected=()):
    return ParsedPage(reviews=list(reviews), rejected=list(rejected), reported_total=total)


class CountingPages:
    """Stands in for the browser. Counts how many pages the collector actually asked for."""

    def __init__(self, pages, then_raise=None):
        self.pages, self.then_raise, self.pulled = pages, then_raise, 0

    def __iter__(self):
        for p in self.pages:
            self.pulled += 1
            yield p
        if self.then_raise:
            raise self.then_raise


def test_full_run_stores_everything_and_reports_summary(store, sample_page):
    r = sample_page.reviews
    pages = CountingPages([page_of(r[:3], total=5), page_of(r[3:], total=5)])

    s = collect_property(SLUG, pages, store, mode="full")

    assert (s.status, s.pages, s.new) == ("ok", 2, 5)
    assert store.count(SLUG) == 5
    assert s.drift is False


def test_incremental_run_stops_at_first_page_with_nothing_new(store, sample_page):
    r = sample_page.reviews
    store.upsert_reviews(r[2:])  # we already have the older three
    pages = CountingPages([page_of(r[:2]), page_of(r[2:]), page_of([]), page_of([])])

    s = collect_property(SLUG, pages, store, mode="incremental")

    assert s.new == 2
    assert pages.pulled == 2  # page 1 (new) + page 2 (all known) then stop, never asked for page 3
    assert store.count(SLUG) == 5


def test_incremental_run_on_empty_database_reads_every_page(store, sample_page):
    r = sample_page.reviews
    pages = CountingPages([page_of(r[:2]), page_of(r[2:4]), page_of(r[4:])])

    s = collect_property(SLUG, pages, store, mode="incremental")

    assert (s.pages, s.new) == (3, 5)


def test_empty_page_ends_the_run(store, sample_page):
    pages = CountingPages([page_of(sample_page.reviews), page_of([]), page_of(sample_page.reviews)])

    s = collect_property(SLUG, pages, store, mode="full")

    assert pages.pulled == 2
    assert s.new == 5


def test_rejected_reviews_are_quarantined_and_counted(store, sample_page):
    bad = RejectedReview(review_key="zzz", reason="rating: too high")
    pages = CountingPages([page_of(sample_page.reviews, rejected=[bad])])

    s = collect_property(SLUG, pages, store, mode="full")

    assert s.rejected == 1
    assert store.quarantined(SLUG)[0]["review_key"] == "zzz"


def test_canary_flags_drift_when_we_collected_far_fewer_than_booking_reports(store, sample_page):
    pages = CountingPages([page_of(sample_page.reviews, total=133)])  # have 5 of 133

    s = collect_property(SLUG, pages, store, mode="full")

    assert s.drift is True
    assert s.reported_total == 133


def test_canary_not_checked_for_incremental_runs(store, sample_page):
    pages = CountingPages([page_of(sample_page.reviews, total=133)])

    s = collect_property(SLUG, pages, store, mode="incremental")

    assert s.drift is False


def test_blocked_run_is_recorded_not_raised_and_keeps_earlier_pages(store, sample_page):
    pages = CountingPages([page_of(sample_page.reviews[:3])], then_raise=BlockedError("HTTP 400 Request not supported"))

    s = collect_property(SLUG, pages, store, mode="full")

    assert s.status == "blocked"
    assert "400" in s.error
    assert store.count(SLUG) == 3
    assert store.latest_run(SLUG)["status"] == "blocked"
    assert store.last_successful_run(SLUG) is None


def test_other_fetch_failures_are_recorded_as_failed(store):
    pages = CountingPages([], then_raise=FetchError("timeout after 3 retries"))

    s = collect_property(SLUG, pages, store, mode="incremental")

    assert s.status == "failed"
    assert store.latest_run(SLUG)["error"] == "timeout after 3 retries"


def test_full_run_marks_reviews_that_vanished(store, sample_page):
    r = sample_page.reviews
    store.upsert_reviews(r)
    pages = CountingPages([page_of(r[:4], total=4)])  # last review is gone from Booking

    collect_property(SLUG, pages, store, mode="full")

    assert store.get(r[4].review_key)["missing_since"] is not None
    assert store.get(r[0].review_key)["missing_since"] is None


def test_layout_change_mid_run_is_recorded_as_failed_with_a_clear_message(store, sample_page):
    from scraper.parse import ParseError

    pages = CountingPages([page_of(sample_page.reviews[:2])],
                          then_raise=ParseError("Unexpected response shape: layout probably changed"))

    s = collect_property(SLUG, pages, store, mode="full")

    assert s.status == "failed"
    assert "layout" in s.error
    assert store.count(SLUG) == 2


def test_a_crashed_earlier_run_is_closed_when_the_next_run_starts(store, sample_page):
    stale = store.start_run(SLUG, "full")  # left 'running' by a killed process

    collect_property(SLUG, CountingPages([page_of(sample_page.reviews)]), store, mode="full")

    statuses = {r["id"]: r["status"] for r in store._db.execute("SELECT id, status FROM scrape_runs")}
    assert statuses[stale] == "interrupted"


def test_ctrl_c_marks_the_run_interrupted_and_keeps_saved_pages(store, sample_page):
    pages = CountingPages([page_of(sample_page.reviews[:3])], then_raise=KeyboardInterrupt())

    with pytest.raises(KeyboardInterrupt):
        collect_property(SLUG, pages, store, mode="full")

    assert store.latest_run(SLUG)["status"] == "interrupted"
    assert store.count(SLUG) == 3
