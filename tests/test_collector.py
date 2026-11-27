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


# ---------------------------------------------------------------- page cap (Phase A)
def numbered_page(sample_page, page_no, size=10, total=3000):
    base = sample_page.reviews[0]
    reviews = [base.model_copy(update={"review_key": f"p{page_no}-r{i}"}) for i in range(size)]
    return page_of(reviews, total=total)


def many_pages(sample_page, count, **kw):
    return CountingPages([numbered_page(sample_page, n, **kw) for n in range(count)])


def test_run_stops_at_the_page_cap_and_is_marked_truncated(store, sample_page):
    pages = many_pages(sample_page, 10)

    s = collect_property(SLUG, pages, store, mode="full", max_pages=3)

    assert s.status == "ok"
    assert s.pages == 3
    assert pages.pulled == 3          # never asked the browser for page 4
    assert s.truncated is True
    assert store.count(SLUG) == 30


def test_truncated_run_does_not_mark_older_reviews_as_missing(store, sample_page):
    store.upsert_reviews([sample_page.reviews[0].model_copy(update={"review_key": "old-review-from-page-90"})])

    collect_property(SLUG, many_pages(sample_page, 10), store, mode="full", max_pages=3)

    assert store.get("old-review-from-page-90")["missing_since"] is None


def test_truncated_run_is_not_a_false_drift_alarm(store, sample_page):
    s = collect_property(SLUG, many_pages(sample_page, 10, total=3000), store, mode="full", max_pages=3)

    assert s.drift is False            # 30 collected, and 30 is exactly what a 3-page cap should give


def test_drift_is_still_caught_inside_the_cap(store, sample_page):
    # cap says we should have ~30 but pages only carry 5 each: parser or layout trouble, not the cap
    s = collect_property(SLUG, many_pages(sample_page, 10, size=5, total=3000), store, mode="full", max_pages=3)

    assert s.truncated is True
    assert s.drift is True


def test_not_truncated_when_everything_fits_under_the_cap(store, sample_page):
    pages = CountingPages([numbered_page(sample_page, 0, size=10, total=20), numbered_page(sample_page, 1, size=10, total=20)])

    s = collect_property(SLUG, pages, store, mode="full", max_pages=2)

    assert s.truncated is False        # reached the cap but also collected everything Booking reports
    assert s.drift is False


def test_no_cap_means_no_truncation(store, sample_page):
    s = collect_property(SLUG, many_pages(sample_page, 5, total=50), store, mode="full")

    assert (s.pages, s.truncated) == (5, False)


def test_ledger_records_why_the_run_stopped(store, sample_page):
    collect_property(SLUG, many_pages(sample_page, 10, total=3000), store, mode="full", max_pages=3)

    row = store.latest_run(SLUG)
    assert row["truncated"] == 1
    assert row["max_pages"] == 3
    assert row["reported_total"] == 3000
    assert row["status"] == "ok"


def test_summary_explains_the_cap_in_plain_words(store, sample_page):
    s = collect_property(SLUG, many_pages(sample_page, 10, total=3000), store, mode="full", max_pages=3)

    assert "newest 30 of 3000" in s.coverage_note
    assert "3-page limit" in s.coverage_note
    assert collect_property(SLUG, many_pages(sample_page, 2, total=20), store, mode="full").coverage_note == ""
