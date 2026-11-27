import sqlite3

import pytest

from insights import metrics
from scraper.store import ReviewStore
from scripts.backfill_coverage import backfill


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "old.db")
    con = sqlite3.connect(path)       # an old-schema database: the ledger has no coverage columns
    con.executescript("""
        CREATE TABLE reviews (review_key TEXT PRIMARY KEY, property TEXT, rating REAL, review_date TEXT);
        INSERT INTO reviews VALUES ('a','venus-potts-point-sydney',5,'2026-11-01'),('b','venus-potts-point-sydney',6,'2026-10-01');
        CREATE TABLE scrape_runs (id INTEGER PRIMARY KEY AUTOINCREMENT, property TEXT NOT NULL, mode TEXT NOT NULL,
            started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL, pages INTEGER DEFAULT 0, new INTEGER DEFAULT 0,
            updated INTEGER DEFAULT 0, rejected INTEGER DEFAULT 0, error TEXT);
        INSERT INTO scrape_runs (property, mode, started_at, finished_at, status, pages, new) VALUES
          ('venus-potts-point-sydney','full','2026-11-27T10:00:00+00:00','2026-11-27T10:07:00+00:00','ok',144,1440);
    """)
    con.commit(); con.close()
    return path


def test_backfill_marks_the_old_run_as_partial_with_the_facts_from_the_console_output(db):
    result = backfill(db, "venus-potts-point-sydney", reported_total=2386, stop_reason="ended_early",
                      evidence="console output of the 27 Nov run: pages=144 stored=1440 reported_total=2386 DRIFT")

    assert result.run_id == 1
    row = ReviewStore(db).latest_run("venus-potts-point-sydney")
    assert (row["truncated"], row["reported_total"], row["stop_reason"]) == (1, 2386, "ended_early")
    assert "backfilled" in row["error"].lower() and "console output" in row["error"]      # provenance is on the record


def test_the_dashboard_then_explains_the_partial_coverage(db):
    backfill(db, "venus-potts-point-sydney", reported_total=2386, stop_reason="ended_early", evidence="console output")

    h = metrics.data_health(db).set_index("property")

    note = h.loc["venus-potts-point-sydney", "coverage_note"]
    assert "2,386" in note and "ended early" in note.lower() and "older" in note.lower()


@pytest.mark.parametrize("bad", ["", "   ", "x" * 1000])
def test_evidence_is_required_and_bounded(db, bad):
    with pytest.raises(ValueError, match="evidence"):
        backfill(db, "venus-potts-point-sydney", reported_total=2386, stop_reason="ended_early", evidence=bad)


def test_only_known_reasons_and_sane_totals_are_accepted(db):
    with pytest.raises(ValueError, match="stop_reason"):
        backfill(db, "venus-potts-point-sydney", reported_total=2386, stop_reason="because", evidence="x")
    with pytest.raises(ValueError, match="reported_total"):
        backfill(db, "venus-potts-point-sydney", reported_total=-5, stop_reason="ended_early", evidence="x")


def test_it_refuses_to_overwrite_coverage_the_scraper_already_recorded(db):
    backfill(db, "venus-potts-point-sydney", reported_total=2386, stop_reason="ended_early", evidence="first")
    with pytest.raises(ValueError, match="already"):
        backfill(db, "venus-potts-point-sydney", reported_total=999, stop_reason="page_cap", evidence="second")


def test_it_refuses_when_there_is_no_successful_run_to_annotate(db):
    with pytest.raises(ValueError, match="no successful run"):
        backfill(db, "chateau-de-venus", reported_total=4305, stop_reason="page_cap", evidence="x")


def test_it_never_touches_the_reviews_themselves(db):
    backfill(db, "venus-potts-point-sydney", reported_total=2386, stop_reason="ended_early", evidence="x")
    assert sqlite3.connect(db).execute("select count(*) from reviews").fetchone()[0] == 2
