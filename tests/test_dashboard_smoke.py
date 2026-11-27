"""Smoke tests for the Streamlit dashboard, run headlessly with streamlit.testing.v1.AppTest.

The tests build their own small synthetic database in tmp_path (they never touch data/demo.db).
Layout and colours cannot be judged here: these tests only prove the app runs and the key
messages and guard-rails (demo banner, empty states, no reviewer identity) are present.
"""
import random
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scraper.config import PROPERTIES  # noqa: E402
from scraper.store import ReviewStore  # noqa: E402
from scripts.make_demo_db import make  # noqa: E402

APP = str(ROOT / "dashboard" / "app.py")


def build_db(path: Path, newest: date = date(2026, 11, 27), weeks: int = 6) -> Path:
    """A small deterministic synthetic DB (reuses the demo generator)."""
    rng = random.Random(7)
    store = ReviewStore(str(path), clock=lambda: datetime(2026, 11, 27, 8, 0, tzinfo=timezone.utc))
    for prop in PROPERTIES:
        reviews, idx = [], 0
        for d in range(weeks * 7):
            for _ in range(rng.choice([0, 1, 1, 2])):
                reviews.append(make(rng, prop.slug, newest - timedelta(days=d), idx))
                idx += 1
        res = store.upsert_reviews(reviews)
        run = store.start_run(prop.slug, "full")
        store.finish_run(run, "ok", pages=1, new=res.new, updated=0, rejected=0, error=None)
    return path


def page_text(at: AppTest) -> str:
    parts = [e.value for e in at.markdown] + [e.value for e in at.info] + [e.value for e in at.warning]
    parts += [e.value for e in at.error] + [e.value for e in at.caption] + [e.value for e in at.subheader]
    parts += [e.value for e in at.header]
    return "\n".join(str(p) for p in parts)


def run_app(monkeypatch, db: Path) -> AppTest:
    monkeypatch.setenv("REVIEWS_DB", str(db))
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    return at


@pytest.fixture
def demo_db(tmp_path):
    return build_db(tmp_path / "azzurro_demo.db")


def test_runs_on_demo_data_without_exception(monkeypatch, demo_db):
    at = run_app(monkeypatch, demo_db)
    assert not at.exception, [e.value for e in at.exception]
    text = page_text(at)
    assert "Review feed" in text
    assert "How to read this" in [e.label for e in at.expander]


def test_demo_banner_shown_for_demo_file(monkeypatch, demo_db):
    text = page_text(run_app(monkeypatch, demo_db))
    assert "DEMO DATA: synthetic, not real guest reviews" in text


def test_no_demo_banner_for_real_file_name(monkeypatch, tmp_path):
    db = build_db(tmp_path / "reviews.db")
    at = run_app(monkeypatch, db)
    assert not at.exception
    assert "DEMO DATA" not in page_text(at)


def test_missing_topics_table_gives_friendly_note(monkeypatch, demo_db):
    at = run_app(monkeypatch, demo_db)
    assert not at.exception
    assert "Topic analysis has not been run yet" in page_text(at)


def test_missing_db_shows_message_not_exception(monkeypatch, tmp_path):
    at = run_app(monkeypatch, tmp_path / "nope_demo.db")
    assert not at.exception
    text = page_text(at)
    assert "No review data found" in text
    assert "make_demo_db.py" in text


def test_db_without_tables_shows_message_not_exception(monkeypatch, tmp_path):
    db = tmp_path / "blank.db"
    sqlite3.connect(db).close()
    at = run_app(monkeypatch, db)
    assert not at.exception, [e.value for e in at.exception]


def test_empty_database_shows_empty_state(monkeypatch, tmp_path):
    db = tmp_path / "empty.db"
    ReviewStore(str(db)).count("x")  # creates the empty schema
    at = run_app(monkeypatch, db)
    assert not at.exception, [e.value for e in at.exception]
    assert "no reviews in the database yet" in page_text(at)


def test_empty_range_shows_empty_state(monkeypatch, tmp_path):
    # Reviews only from 2024, so "This week so far" (today) has none.
    db = build_db(tmp_path / "old_demo.db", newest=date(2024, 3, 31), weeks=4)
    monkeypatch.setenv("REVIEWS_DB", str(db))
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception
    pick(at, period="This week so far")
    assert not at.exception, [e.value for e in at.exception]
    assert "No reviews between" in page_text(at)


def test_no_hotel_selected_shows_hint(monkeypatch, demo_db):
    at = run_app(monkeypatch, demo_db)
    pick(at, hotels=[])
    assert not at.exception
    assert "Choose at least one hotel" in page_text(at)


def test_feed_never_mentions_reviewer_identity(monkeypatch, demo_db):
    at = run_app(monkeypatch, demo_db)
    assert not at.exception
    pick(at, period="All time")
    assert not at.exception
    text = page_text(at).lower()
    assert "az-review" in text  # the feed really rendered cards
    assert "username" not in text and "avatar" not in text
    assert "reviewer name" not in text.replace("reviewer names are never stored", "")


def test_review_text_is_escaped(monkeypatch, tmp_path):
    db = build_db(tmp_path / "x_demo.db")
    con = sqlite3.connect(db)
    con.execute("UPDATE reviews SET disliked = '<script>alert(1)</script> =HYPERLINK(1)'")
    con.commit()
    con.close()
    at = run_app(monkeypatch, db)
    pick(at, period="All time")
    assert not at.exception
    text = page_text(at)
    assert "<script>" not in text
    assert "&lt;script&gt;" in text


def test_feed_filters_and_pagination_run(monkeypatch, demo_db):
    at = run_app(monkeypatch, demo_db)
    pick(at, period="All time")
    at.checkbox(key="feed_neg").check().run()
    assert not at.exception
    at.checkbox(key="feed_noreply").check().run()
    at.text_input(key="feed_search").set_value("zzzz-no-such-word").run()
    assert not at.exception
    assert "No reviews match these filters" in page_text(at)
    at.text_input(key="feed_search").set_value("").run()
    at.checkbox(key="feed_neg").uncheck().run()
    at.checkbox(key="feed_noreply").uncheck().run()
    at.button(key="feed_next").click().run()
    assert not at.exception
    assert "Page 2 of" in page_text(at)


def test_rating_only_reviews_get_compact_card_and_filter(monkeypatch, tmp_path):
    db = build_db(tmp_path / "rating_only_demo.db")
    con = sqlite3.connect(db)
    con.execute("UPDATE reviews SET liked = NULL, disliked = '' WHERE rowid % 3 = 0")
    con.commit()
    con.close()
    at = run_app(monkeypatch, db)
    pick(at, period="All time")
    assert not at.exception, [e.value for e in at.exception]
    assert "Rating only, no written comment" in page_text(at)
    at.checkbox(key="feed_text").check().run()
    assert not at.exception
    assert "Rating only, no written comment" not in page_text(at)


def test_runs_with_topic_analysis_present(monkeypatch, demo_db):
    from insights.pipeline import classify_all

    classify_all(str(demo_db))
    at = run_app(monkeypatch, demo_db)
    assert not at.exception, [e.value for e in at.exception]
    text = page_text(at)
    assert "Topic analysis has not been run yet" not in text
    pick(at, period="Last 12 weeks")
    at.radio(key="topic_view").set_value("Praise").run()
    assert not at.exception, [e.value for e in at.exception]
    assert "az-chip" in page_text(at)
    at.selectbox(key="feed_topic").select("negative:noise").run()
    assert not at.exception, [e.value for e in at.exception]


# ---------------------------------------------------------------- page cap shown to staff (Phase A)
def capped_db(tmp_path):
    db = build_db(tmp_path / "azzurro_demo.db")
    store = ReviewStore(str(db), clock=lambda: datetime(2026, 11, 27, 9, 0, tzinfo=timezone.utc))
    run = store.start_run("chateau-de-venus", "full")
    store.finish_run(run, "ok", 200, 0, 0, 0, None, truncated=True, reported_total=3120, max_pages=200)
    return db


def test_page_cap_is_explained_in_the_banner_and_health_table(tmp_path, monkeypatch):
    at = run_app(monkeypatch, capped_db(tmp_path))

    assert not at.exception
    text = page_text(at)
    assert "Darling Harbour" in text and "page limit" in text
    health_tables = [df.value for df in at.dataframe]
    assert any("Coverage" in t.columns and t["Coverage"].astype(str).str.contains("page limit").any()
               for t in health_tables)


def test_no_cap_note_when_nothing_was_truncated(demo_db, monkeypatch):
    at = run_app(monkeypatch, demo_db)

    assert not at.exception
    assert "page limit" not in page_text(at)

PERIOD_ALIASES = {"This week so far": "This week", "Latest full week": "Last week", "Last 4 weeks": "Last 30 days",
                  "Last 12 weeks": "All time", "Custom dates": "Custom"}


def pick(at, period=None, hotels=None):
    """Set the top filter bar (filters apply as soon as they change)."""
    if period is not None:
        at.session_state["f_period"] = PERIOD_ALIASES.get(period, period)
    if hotels is not None:
        at.session_state["f_hotels"] = hotels
    at.run()
    return at
