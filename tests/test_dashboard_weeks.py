"""Week handling on the dashboard: which week is "the latest full week", and how the page labels it.

The dashboard must take "today" from the Sydney clock (dashboard.ui.data.today_sydney), not from the newest
review. These tests freeze that clock so they do not depend on the day they are run. Synthetic data only,
built in tmp_path.
"""
from datetime import date, datetime, timezone

import pytest
from streamlit.testing.v1 import AppTest

import dashboard.ui.data as D
from scraper.config import PROPERTIES
from scraper.models import Review
from scraper.store import ReviewStore
from tests.test_dashboard_smoke import APP, page_text

HOTEL = PROPERTIES[0].slug
OTHER = PROPERTIES[1].slug


def build_db(path, rows, clock=datetime(2026, 11, 27, 8, 0, tzinfo=timezone.utc)):
    """rows: (date, rating) for the first hotel, or (date, rating, slug). Every review has a short English comment."""
    store = ReviewStore(str(path), clock=lambda: clock)
    by_slug: dict[str, list[Review]] = {}
    for i, row in enumerate(rows):
        day, rating = row[0], row[1]
        slug = row[2] if len(row) > 2 else HOTEL
        by_slug.setdefault(slug, []).append(Review(
            review_key=f"wk-{slug}-{i}", property=slug, rating=rating, review_date=day, title=None,
            liked="Nice location.", disliked="The room was dirty." if rating < 5 else None, language="en"))
    for slug, reviews in by_slug.items():
        res = store.upsert_reviews(reviews)
        run = store.start_run(slug, "full")
        store.finish_run(run, "ok", pages=1, new=res.new, updated=0, rejected=0, error=None)
    store.close()
    return path


def run_frozen(monkeypatch, db, today):
    monkeypatch.setattr(D, "today_sydney", lambda: today)
    monkeypatch.setenv("REVIEWS_DB", str(db))
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


# ------------------------------------------------------------------------------ the clock
def test_today_sydney_is_a_date_in_the_sydney_zone():
    from zoneinfo import ZoneInfo
    assert D.today_sydney() == datetime.now(ZoneInfo("Australia/Sydney")).date()


# ------------------------------------------------------------------------------ latest full week
def test_newest_review_on_a_sunday_still_counts_that_week_on_the_next_monday(monkeypatch, tmp_path):
    db = build_db(tmp_path / "reviews.db", [(date(2026, 11, 17), 5.0), (date(2026, 11, 24), 7.0), (date(2026, 11, 29), 6.0)])
    at = run_frozen(monkeypatch, db, date(2026, 11, 30))
    text = page_text(at)
    assert "Week of Mon 23 Nov" in text           # 23 to 29 Nov is finished on Monday 30 Nov
    assert "Week of Mon 16 Nov" not in text.replace("Previous week (Mon 16 Nov)", "")
    assert "Week of 23 Nov at a glance" in text


def test_stale_snapshot_picks_the_latest_week_with_data_and_says_how_old_it_is(monkeypatch, tmp_path):
    rows = [(date(2026, 11, 3), 5.0), (date(2026, 11, 4), 6.0), (date(2026, 11, 10), 7.0), (date(2026, 11, 10), 8.0)]
    at = run_frozen(monkeypatch, build_db(tmp_path / "reviews.db", rows), date(2026, 11, 27))
    text = page_text(at)
    assert "Week of Mon 9 Nov" in text
    assert "No reviews between" not in text
    assert "newest review in this data is from Tue 10 Nov 2026" in text
    assert "17 days ago" in text


def test_fresh_data_gets_no_age_warning(monkeypatch, tmp_path):
    rows = [(date(2026, 11, 17), 5.0), (date(2026, 11, 24), 7.0)]
    text = page_text(run_frozen(monkeypatch, build_db(tmp_path / "reviews.db", rows), date(2026, 11, 25)))
    assert "newest review in this data" not in text


def test_newest_review_mid_week_uses_the_last_finished_week(monkeypatch, tmp_path):
    rows = [(date(2026, 11, 10), 6.0), (date(2026, 11, 18), 5.0), (date(2026, 11, 25), 7.0)]
    at = run_frozen(monkeypatch, build_db(tmp_path / "reviews.db", rows), date(2026, 11, 25))
    text = page_text(at)
    assert "Week of Mon 16 Nov" in text
    assert "Week of 16 Nov at a glance" in text


def test_this_week_so_far_preset_follows_the_sydney_clock(monkeypatch, tmp_path):
    rows = [(date(2026, 11, 18), 5.0), (date(2026, 11, 25), 7.0)]
    at = run_frozen(monkeypatch, build_db(tmp_path / "reviews.db", rows), date(2026, 11, 25))
    at.sidebar.selectbox(key="range_preset").select("This week so far").run()
    assert not at.exception, [e.value for e in at.exception]
    assert "Mon 23 Nov to Sun 29 Nov 2026" in page_text(at)


# ------------------------------------------------------------------------------ honest labels
LAST_WEEK_ROWS = [(date(2026, 11, 9), 6.0), (date(2026, 11, 10), 6.0),
                  (date(2026, 11, 16), 5.0), (date(2026, 11, 17), 5.0), (date(2026, 11, 18), 5.0)]
THIS_WEEK_ROWS = [(date(2026, 11, 23), 6.0), (date(2026, 11, 24), 6.0), (date(2026, 11, 25), 7.0)]


def test_cards_are_labelled_with_dates_not_this_week(monkeypatch, tmp_path):
    at = run_frozen(monkeypatch, build_db(tmp_path / "reviews.db", LAST_WEEK_ROWS), date(2026, 11, 25))
    text = page_text(at)
    assert "Guest score, week of Mon 16 Nov" in text
    assert "Previous week (Mon 9 Nov)" in text
    assert "Reviews, week of Mon 16 Nov" in text
    assert "Guest score this week" not in text
    assert "Reviews this week" not in text
    assert "This week at a glance" not in text
    assert "Week of 16 Nov at a glance" in text
    assert "3 reviews in the week of Mon 16 Nov" in text       # hotel card
    assert "this week so far" not in text.lower()   # nothing claims the focus is the live week


def test_strip_compares_the_part_week_with_the_last_full_week(monkeypatch, tmp_path):
    at = run_frozen(monkeypatch, build_db(tmp_path / "reviews.db", LAST_WEEK_ROWS + THIS_WEEK_ROWS), date(2026, 11, 25))
    text = page_text(at)
    assert ("This week so far (Mon 23 Nov to today): 6.3 from 3 reviews, compared with 5.0 for the last full week. "
            "A part-week average moves more, so read it with the count.") in text
    assert "Only 3 reviews so far" in text        # n < LOW_SAMPLE_BELOW: small-sample caution


def test_strip_sits_directly_under_the_score_cards(monkeypatch, tmp_path):
    at = run_frozen(monkeypatch, build_db(tmp_path / "reviews.db", LAST_WEEK_ROWS + THIS_WEEK_ROWS), date(2026, 11, 25))
    blocks = [e.value for e in at.markdown]
    kpi = next(i for i, b in enumerate(blocks) if "Positive vs negative" in b)
    strip = next(i for i, b in enumerate(blocks) if "This week so far (Mon 23 Nov to today)" in b)
    hotels = next(i for i, b in enumerate(blocks) if "3 reviews in the week of Mon 16 Nov" in b)
    assert kpi < strip < hotels


def test_no_small_sample_caution_when_the_part_week_has_enough_reviews(monkeypatch, tmp_path):
    rows = LAST_WEEK_ROWS + THIS_WEEK_ROWS + [(date(2026, 11, 25), 8.0), (date(2026, 11, 25), 8.0)]
    text = page_text(run_frozen(monkeypatch, build_db(tmp_path / "reviews.db", rows), date(2026, 11, 25)))
    assert "from 5 reviews" in text
    assert "so far, so treat" not in text


def test_no_strip_when_the_focus_week_is_the_current_week(monkeypatch, tmp_path):
    at = run_frozen(monkeypatch, build_db(tmp_path / "reviews.db", LAST_WEEK_ROWS + THIS_WEEK_ROWS), date(2026, 11, 25))
    at.sidebar.selectbox(key="range_preset").select("This week so far").run()
    assert not at.exception, [e.value for e in at.exception]
    text = page_text(at)
    assert "to today)" not in text
    assert "Guest score, this week so far" in text
    assert "This week so far at a glance" in text
    assert "3 reviews this week so far" in text       # hotel card


def test_no_strip_when_the_current_week_has_no_reviews(monkeypatch, tmp_path):
    text = page_text(run_frozen(monkeypatch, build_db(tmp_path / "reviews.db", LAST_WEEK_ROWS), date(2026, 11, 25)))
    assert "to today)" not in text


def test_strip_counts_only_the_selected_hotels(monkeypatch, tmp_path):
    rows = LAST_WEEK_ROWS + [(d, r, OTHER) for d, r in THIS_WEEK_ROWS]
    at = run_frozen(monkeypatch, build_db(tmp_path / "reviews.db", rows), date(2026, 11, 25))
    assert "to today)" in page_text(at)
    at.sidebar.multiselect(key="props").set_value([PROPERTIES[0].name]).run()
    assert not at.exception, [e.value for e in at.exception]
    assert "to today)" not in page_text(at)


def test_strip_with_an_empty_last_full_week_says_so(monkeypatch, tmp_path):
    rows = [(date(2026, 11, 3), 6.0)] + THIS_WEEK_ROWS         # nothing in the weeks of 9 and 16 Nov
    at = run_frozen(monkeypatch, build_db(tmp_path / "reviews.db", rows), date(2026, 11, 25))
    text = page_text(at)
    assert "Week of Mon 2 Nov" in text         # latest finished week with data
    assert "This week so far (Mon 23 Nov to today): 6.3 from 3 reviews" in text
    assert "compared with 6.0 for the week of Mon 2 Nov" in text      # not "the last full week": that one is empty


def test_hostile_text_cannot_reach_the_strip(monkeypatch, tmp_path):
    db = build_db(tmp_path / "reviews.db", LAST_WEEK_ROWS + THIS_WEEK_ROWS)
    at = run_frozen(monkeypatch, db, date(2026, 11, 25))
    assert "<script" not in "\n".join(e.value for e in at.markdown)


# ------------------------------------------------------------------------------ pure label helper
def test_week_labels_for_the_current_week():
    lab = D.week_labels(date(2026, 11, 23), date(2026, 11, 25))
    assert lab.current is True
    assert lab.heading == "This week so far at a glance"
    assert lab.in_week == "this week so far"


def test_week_labels_for_an_older_week():
    lab = D.week_labels(date(2026, 11, 16), date(2026, 11, 25))
    assert lab.current is False
    assert lab.heading == "Week of 16 Nov at a glance"
    assert lab.score == "Guest score, week of Mon 16 Nov"
    assert lab.previous == "Previous week (Mon 9 Nov)"
    assert lab.in_week == "in the week of Mon 16 Nov"
