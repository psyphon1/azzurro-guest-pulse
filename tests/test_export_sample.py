import csv
import io
import sqlite3
from datetime import date, timedelta

import pytest

from insights.pipeline import classify_all
from scraper.config import PROPERTIES
from scraper.models import Review
from scraper.store import ReviewStore
from scripts.export_sample import export_sample

SLUGS = [p.slug for p in PROPERTIES]


@pytest.fixture
def src(tmp_path):
    path = str(tmp_path / "live.db")
    store = ReviewStore(path)
    for slug in SLUGS:
        reviews = [Review(review_key=f"{slug}-{i:03d}", property=slug, rating=3.0 + (i % 7),
                          review_date=date(2026, 11, 1) - timedelta(days=i), language="en",
                          liked="Great location", disliked="The room was dirty and noisy" if i % 2 else None,
                          reviewer_country="Australia", traveller_type="Couple", room_type="Standard Double",
                          host_reply="Thanks for your feedback" if i % 3 == 0 else None) for i in range(20)]
        store.upsert_reviews(reviews)
        run = store.start_run(slug, "full")
        store.finish_run(run, "ok", 2, 20, 0, 0, None, truncated=True, reported_total=500, max_pages=200,
                         stop_reason="date_window", since_days=365)
    store.close()
    classify_all(path)
    return path


def rows_of(csv_path):
    return list(csv.DictReader(io.StringIO(open(csv_path, encoding="utf-8-sig").read())))


def test_csv_has_the_newest_n_reviews_per_hotel_for_all_four_hotels(src, tmp_path):
    out = export_sample(src, str(tmp_path / "s.csv"), per_property=5, sample_db_path=None)

    rows = rows_of(out.csv_path)
    assert len(rows) == 20
    assert {r["Hotel"] for r in rows} == {p.name for p in PROPERTIES}
    olympic = [r for r in rows if r["Hotel"] == "Olympic Hotel Paddington"]
    assert [r["Date"] for r in olympic] == sorted((r["Date"] for r in olympic), reverse=True)
    assert olympic[0]["Date"] == "2026-11-01"                      # newest first
    assert out.per_property == {p.slug: 5 for p in PROPERTIES}


def test_csv_has_topics_and_no_reviewer_identity(src, tmp_path):
    out = export_sample(src, str(tmp_path / "s.csv"), per_property=5, sample_db_path=None)

    header = set(rows_of(out.csv_path)[0])
    assert {"Complaint topics", "Praise topics", "Score", "What guests disliked"} <= header
    assert not {h for h in header if any(w in h.lower() for w in ("name", "username", "avatar", "email"))}
    assert "Cleanliness" in "".join(r["Complaint topics"] for r in rows_of(out.csv_path))


def test_csv_cells_are_safe_in_a_spreadsheet_and_contact_details_are_masked(src, tmp_path):
    store = ReviewStore(src)
    store.upsert_reviews([Review(review_key="evil-1", property=SLUGS[0], rating=5.0, review_date=date(2026, 11, 2), language="en",
                                 liked='=HYPERLINK("http://evil.example","click")',
                                 disliked="Text me on 0412 345 678 or jo.smith@example.com")])
    store.close()

    out = export_sample(src, str(tmp_path / "s.csv"), per_property=5, sample_db_path=None)

    row = next(r for r in rows_of(out.csv_path) if r["Date"] == "2026-11-02")
    assert row["What guests liked"].startswith(("'", " ")) and not row["What guests liked"].startswith("=")
    assert "jo.smith@example.com" not in row["What guests disliked"] and "0412 345 678" not in row["What guests disliked"]


def test_sample_database_holds_the_same_reviews_topics_and_runs(src, tmp_path):
    out = export_sample(src, str(tmp_path / "s.csv"), per_property=5, sample_db_path=str(tmp_path / "sample.db"))

    con = sqlite3.connect(out.sample_db_path)
    assert con.execute("select count(*) from reviews").fetchone()[0] == 20
    assert con.execute("select count(distinct property) from reviews").fetchone()[0] == 4
    assert con.execute("select count(*) from review_topics where review_key not in (select review_key from reviews)").fetchone()[0] == 0
    assert con.execute("select count(*) from review_topics").fetchone()[0] > 0
    runs = con.execute("select count(*), max(truncated), max(stop_reason) from scrape_runs").fetchone()
    assert runs == (4, 1, "date_window")                           # coverage information travels with the sample
    ReviewStore(out.sample_db_path)                                  # opens as a normal store


def test_export_never_modifies_the_source_database(src, tmp_path):
    before = sqlite3.connect(src).execute("select count(*) from reviews").fetchone()
    export_sample(src, str(tmp_path / "s.csv"), per_property=5, sample_db_path=str(tmp_path / "sample.db"))
    assert sqlite3.connect(src).execute("select count(*) from reviews").fetchone() == before


def test_a_hotel_with_no_data_is_reported_not_hidden(tmp_path):
    path = str(tmp_path / "partial.db")
    store = ReviewStore(path)
    store.upsert_reviews([Review(review_key="o1", property="olympic-paddington", rating=7.0, review_date=date(2026, 11, 1))])
    store.close()

    out = export_sample(path, str(tmp_path / "s.csv"), per_property=5, sample_db_path=None)

    assert out.per_property["venus-surry-hills"] == 0
    assert "venus-surry-hills" in out.missing_hotels


def test_refuses_to_overwrite_the_live_database_with_its_own_sample(src):
    with pytest.raises(ValueError):
        export_sample(src, "x.csv", per_property=5, sample_db_path=src)


# ---------------------------------------------------------------- red team on the export script itself
def test_csv_path_may_not_be_the_live_database_or_the_sample_database(src, tmp_path):
    with pytest.raises(ValueError, match="live database"):
        export_sample(src, src, per_property=5, sample_db_path=None)                       # would overwrite the database with CSV text
    sample = str(tmp_path / "sample.db")
    with pytest.raises(ValueError):
        export_sample(src, sample, per_property=5, sample_db_path=sample)
    assert sqlite3.connect(src).execute("select count(*) from reviews").fetchone()[0] == 80   # still intact


def test_an_unrelated_existing_file_is_never_deleted_by_the_sample_step(src, tmp_path):
    precious = tmp_path / "important.db"
    precious.write_text("my thesis, not a database")

    with pytest.raises(ValueError, match="not a previous sample"):
        export_sample(src, str(tmp_path / "s.csv"), per_property=5, sample_db_path=str(precious))

    assert precious.read_text() == "my thesis, not a database"


def test_a_previous_sample_database_can_be_replaced(src, tmp_path):
    target = str(tmp_path / "sample.db")
    export_sample(src, str(tmp_path / "s.csv"), per_property=5, sample_db_path=target)
    out = export_sample(src, str(tmp_path / "s.csv"), per_property=3, sample_db_path=target)      # second run overwrites the first
    assert sqlite3.connect(out.sample_db_path).execute("select count(*) from reviews").fetchone()[0] == 12


@pytest.mark.parametrize("bad", [0, -1, 10**9])
def test_per_property_is_bounded(src, tmp_path, bad):
    with pytest.raises(ValueError, match="per_property"):
        export_sample(src, str(tmp_path / "s.csv"), per_property=bad, sample_db_path=None)


def test_a_symlink_to_the_live_database_is_still_recognised(src, tmp_path):
    link = tmp_path / "innocent.db"
    link.symlink_to(src)
    with pytest.raises(ValueError):
        export_sample(src, str(tmp_path / "s.csv"), per_property=5, sample_db_path=str(link))


def test_committed_real_review_fixtures_contain_no_email_or_phone_numbers():
    import json
    from pathlib import Path

    from dashboard.ui.privacy import looks_like_pii

    checked = 0
    for path in Path(__file__).parent.joinpath("fixtures").glob("*.json"):
        data = json.loads(path.read_text())
        if not (isinstance(data, list) and data and isinstance(data[0], dict)):
            continue                                   # raw API payloads are covered by the parser tests
        checked += 1
        for case in data:
            for field in ("liked", "disliked", "title", "host_reply"):
                assert not looks_like_pii(case.get(field) or ""), f"{path.name}: {case.get('id')} has contact details"
    assert checked >= 2                                # both gold files were really inspected


def test_the_sample_database_can_be_tagged_again_by_the_pipeline(src, tmp_path):
    # Bug found by the deployment review: the copied tag tables had no primary keys, so the pipeline's
    # INSERT OR REPLACE / ON CONFLICT logic failed on the sample database.
    out = export_sample(src, str(tmp_path / "s.csv"), per_property=5, sample_db_path=str(tmp_path / "sample.db"))
    before = sqlite3.connect(out.sample_db_path).execute("select count(*) from review_topics").fetchone()[0]

    result = classify_all(out.sample_db_path)                      # must not raise

    after = sqlite3.connect(out.sample_db_path).execute("select count(*) from review_topics").fetchone()[0]
    assert after == before and result.reviews_seen == 20


def test_tag_tables_in_the_sample_keep_their_primary_keys(src, tmp_path):
    out = export_sample(src, str(tmp_path / "s.csv"), per_property=5, sample_db_path=str(tmp_path / "sample.db"))
    con = sqlite3.connect(out.sample_db_path)
    pk_topics = [r[1] for r in con.execute("PRAGMA table_info(review_topics)") if r[5]]
    pk_state = [r[1] for r in con.execute("PRAGMA table_info(review_topics_state)") if r[5]]
    assert set(pk_topics) == {"review_key", "topic", "polarity"} and pk_state == ["review_key"]


def test_the_sample_connection_is_opened_in_uri_mode_so_attach_works_on_every_python(src, tmp_path, monkeypatch):
    # Found by the fresh-clone review: on Python 3.11 ATTACH with a file: URI fails unless the connection that runs
    # it was opened with uri=True (3.13/3.15 are lenient). Assert the requirement itself, not the interpreter.
    import scripts.export_sample as mod

    real_connect, calls = sqlite3.connect, []

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real_connect(*args, **kwargs)

    monkeypatch.setattr(mod.sqlite3, "connect", spy)
    mod.export_sample(src, str(tmp_path / "s.csv"), per_property=5, sample_db_path=str(tmp_path / "sample.db"))

    uri_calls = [kw for args, kw in calls if str(args[0]).startswith("file:")]
    assert uri_calls, "the sample database should be opened through a file: URI"
    assert all(kw.get("uri") is True for kw in uri_calls)      # a file: URI without uri=True is a plain, wrong file name
