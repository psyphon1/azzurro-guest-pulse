"""The dashboard when one hotel has NO reviews at all (collection blocked) and two others are only partly covered.

Mirrors the real situation: Central Sydney (venus-surry-hills) was blocked by Booking.com twice and has zero
reviews; Potts Point and Darling Harbour stopped early / at the page limit so older history is missing.
Synthetic data only, built in tmp_path (never the real databases).
"""
import random
import sqlite3
from datetime import date, datetime, timedelta, timezone

import pytest

from scraper.config import PROPERTIES
from scraper.store import ReviewStore
from scripts.make_demo_db import make
from tests.test_dashboard_smoke import page_text, run_app

EMPTY = "venus-surry-hills"
BLOCK_ERR = "Bot check did not clear and the reviews section never appeared"
NEWEST = date(2026, 11, 27)


def build_blocked_db(path, error=BLOCK_ERR, weeks=6):
    rng = random.Random(11)
    store = ReviewStore(str(path), clock=lambda: datetime(2026, 11, 27, 8, 0, tzinfo=timezone.utc))
    for prop in PROPERTIES:
        if prop.slug == EMPTY:
            for _ in range(2):   # blocked twice, never a review
                run = store.start_run(prop.slug, "full")
                store.finish_run(run, "blocked", pages=0, new=0, updated=0, rejected=0, error=error)
            continue
        reviews, idx = [], 0
        for d in range(weeks * 7):
            for _ in range(rng.choice([1, 1, 2])):
                reviews.append(make(rng, prop.slug, NEWEST - timedelta(days=d), idx))
                idx += 1
        res = store.upsert_reviews(reviews)
        run = store.start_run(prop.slug, "full")
        trunc = {"venus-potts-point-sydney": ("ended_early", 400), "chateau-de-venus": ("page_cap", 900)}.get(prop.slug)
        store.finish_run(run, "ok", pages=3, new=res.new, updated=0, rejected=0, error=None,
                         truncated=bool(trunc), reported_total=trunc[1] if trunc else None,
                         max_pages=3 if trunc else None, stop_reason=trunc[0] if trunc else None)
    store.close()
    return path


@pytest.fixture
def db(tmp_path):
    return build_blocked_db(tmp_path / "reviews.db")


def test_no_exception_and_all_four_hotels_selectable(monkeypatch, db):
    at = run_app(monkeypatch, db)
    assert not at.exception, [e.value for e in at.exception]
    assert [p.name for p in PROPERTIES] == list(at.sidebar.multiselect(key="props").options)
    assert len(at.sidebar.multiselect(key="props").value) == 4


def test_hotel_card_for_hotel_without_reviews(monkeypatch, db):
    text = page_text(run_app(monkeypatch, db))
    assert "No reviews collected for this hotel yet" in text
    assert "Booking.com blocked" in text
    assert "Central Sydney" in text


def test_hotel_with_reviews_but_none_this_week_says_so(monkeypatch, db):
    con = sqlite3.connect(db)
    con.execute("UPDATE reviews SET review_date = '2026-10-01' WHERE property = 'chateau-de-venus'")
    con.commit()
    con.close()
    import dashboard.ui.data as D
    monkeypatch.setattr(D, "today_sydney", lambda: NEWEST)      # Fri 27 Nov: the latest full week is the one of Mon 16 Nov
    text = page_text(run_app(monkeypatch, db))
    assert "No reviews in the week of Mon 16 Nov" in text     # the card names the week by its dates
    assert text.count("No reviews collected for this hotel yet") == 1


def test_banner_names_empty_and_partial_hotels(monkeypatch, db):
    text = page_text(run_app(monkeypatch, db))
    assert "Central Sydney: no reviews collected yet" in text
    assert "Data is up to date" not in text
    assert "Potts Point: only part of the history" in text
    assert "Darling Harbour: only part of the history" in text
    from dashboard.ui.style import esc
    from insights.metrics import data_health
    notes = [n for n in data_health(db)["coverage_note"] if n]
    assert len(notes) == 2
    for note in notes:                                         # the ledger's coverage note is reused word for word
        assert esc(note) in text
    assert "Central Sydney: no successful update" not in text   # no misleading "48 hours" line for a never-collected hotel


def test_portfolio_numbers_say_how_many_hotels(monkeypatch, db):
    text = page_text(run_app(monkeypatch, db))
    assert "Based on 3 of 4 hotels" in text
    assert text.count("Based on 3 of 4 hotels") == 1         # said once, under the week heading


def test_only_the_empty_hotel_selected_gives_friendly_state(monkeypatch, db):
    at = run_app(monkeypatch, db)
    at.sidebar.multiselect(key="props").set_value(["Central Sydney"]).run()
    assert not at.exception, [e.value for e in at.exception]
    text = page_text(at)
    assert "No reviews collected for this hotel yet" in text
    assert "No reviews have been collected for the selected hotel" in text
    assert "Never collected" in "".join(df.value.to_csv() for df in at.dataframe)


def test_health_table_shows_never_collected_and_reason(monkeypatch, db):
    at = run_app(monkeypatch, db)
    table = next(d.value for d in at.dataframe)
    row = table[table["Hotel"] == "Central Sydney"].iloc[0]
    assert row["Reviews stored"] == 0
    assert row["Last successful update (Sydney)"] == "Never collected"
    assert row["Latest attempt"] == "Blocked by Booking.com"
    assert "never appeared" in row["Problem details"]
    assert "never" not in str(table[table["Hotel"] == "Potts Point"].iloc[0]["Last successful update (Sydney)"]).lower()


def test_blocked_reason_is_escaped(monkeypatch, tmp_path):
    db = build_blocked_db(tmp_path / "reviews.db", error="<script>alert(1)</script> blocked")
    at = run_app(monkeypatch, db)
    assert not at.exception
    html_text = "\n".join(e.value for e in at.markdown)
    assert "<script>" not in html_text
    table = next(d.value for d in at.dataframe)
    assert "<script>" not in "".join(table["Problem details"].astype(str))


def test_topic_views_mention_hotel_without_reviews(monkeypatch, db):
    from insights.pipeline import classify_all
    classify_all(str(db))
    at = run_app(monkeypatch, db)
    assert not at.exception, [e.value for e in at.exception]
    text = page_text(at)
    assert "Central Sydney has no reviews" in text            # trends / heatmap / feed notes
