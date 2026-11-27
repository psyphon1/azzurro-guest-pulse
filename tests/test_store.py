from datetime import datetime, timezone

import pytest

from scraper.store import ReviewStore


class FakeClock:
    def __init__(self):
        self.t = datetime(2026, 11, 20, 9, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, days):
        from datetime import timedelta
        self.t += timedelta(days=days)


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def store(clock):
    return ReviewStore(":memory:", clock=clock)


def test_new_reviews_are_inserted(store, sample_page):
    result = store.upsert_reviews(sample_page.reviews)

    assert (result.new, result.updated, result.unchanged) == (5, 0, 0)
    assert store.count("olympic-paddington") == 5


def test_saving_the_same_reviews_twice_creates_no_duplicates(store, sample_page):
    store.upsert_reviews(sample_page.reviews)
    result = store.upsert_reviews(sample_page.reviews)

    assert (result.new, result.updated, result.unchanged) == (0, 0, 5)
    assert store.count("olympic-paddington") == 5


def test_edited_review_is_updated_not_duplicated_and_keeps_first_seen(store, clock, sample_page):
    store.upsert_reviews(sample_page.reviews)
    first_seen = store.get("b5dd03c083f5278b")["first_seen"]

    clock.advance(days=3)
    edited = [r.model_copy() for r in sample_page.reviews]
    edited[0].host_reply = "Hotel replied later."
    result = store.upsert_reviews(edited)

    row = store.get("b5dd03c083f5278b")
    assert (result.new, result.updated, result.unchanged) == (0, 1, 4)
    assert store.count("olympic-paddington") == 5
    assert row["host_reply"] == "Hotel replied later."
    assert row["first_seen"] == first_seen
    assert row["last_seen"] != first_seen


def test_known_keys_lets_the_collector_spot_reviews_it_already_has(store, sample_page):
    store.upsert_reviews(sample_page.reviews[:2])

    assert store.known_keys("olympic-paddington") == {"b5dd03c083f5278b", "cdea2877d7771ee9"}


def test_rejected_reviews_are_kept_in_quarantine(store, raw_payload):
    from scraper.parse import parse_page

    raw_payload["data"]["reviewListFrontend"]["reviewCard"][0]["reviewScore"] = 99
    page = parse_page(raw_payload, "olympic-paddington")

    store.quarantine("olympic-paddington", page.rejected)

    rows = store.quarantined("olympic-paddington")
    assert len(rows) == 1
    assert rows[0]["review_key"] == "b5dd03c083f5278b"
    assert "rating" in rows[0]["reason"]


def test_run_ledger_records_outcome_and_latest_success(store, clock):
    run_id = store.start_run("olympic-paddington", mode="incremental")
    clock.advance(days=0)
    store.finish_run(run_id, status="ok", pages=3, new=7, updated=1, rejected=0, error=None)

    clock.advance(days=1)
    bad = store.start_run("olympic-paddington", mode="incremental")
    store.finish_run(bad, status="blocked", pages=0, new=0, updated=0, rejected=0, error="HTTP 400")

    last_ok = store.last_successful_run("olympic-paddington")
    assert last_ok["new"] == 7
    assert store.latest_run("olympic-paddington")["status"] == "blocked"


def test_unfinished_runs_are_closed_as_interrupted(store):
    old = store.start_run("olympic-paddington", mode="full")  # process was killed, never finished
    other = store.start_run("venus-surry-hills", mode="full")

    closed = store.close_stale_runs("olympic-paddington")

    assert closed == 1
    row = store.latest_run("olympic-paddington")
    assert row["id"] == old and row["status"] == "interrupted"
    assert "did not finish" in row["error"]
    assert store.latest_run("venus-surry-hills")["status"] == "running"  # other property untouched
