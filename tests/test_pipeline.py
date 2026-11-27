import sqlite3
from datetime import date

import pytest

from insights import pipeline
from insights.pipeline import ClassifyResult, classify_all, main
from scraper.models import Review
from scraper.store import ReviewStore


def make_review(key="r1", liked="Great location.", disliked="The room was dirty.", **kw):
    return Review(review_key=key, property="olympic-paddington", rating=6.0,
                  review_date=date(2026, 11, 20), liked=liked, disliked=disliked, **kw)


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "reviews.db")


@pytest.fixture
def store(db_path):
    return ReviewStore(db_path)


def tags(db_path, key=None):
    db = sqlite3.connect(db_path)
    sql = "SELECT review_key, topic, polarity, evidence, method, taxonomy_version FROM review_topics"
    rows = db.execute(sql + (" WHERE review_key=?" if key else "") + " ORDER BY 1,2,3", (key,) if key else ())
    out = rows.fetchall()
    db.close()
    return out


def test_classify_all_writes_tags_with_contract_columns(db_path, store):
    store.upsert_reviews([make_review()])

    result = classify_all(db_path)

    assert result == ClassifyResult(reviews_seen=1, reviews_classified=1, reviews_skipped=0, tags_written=2)
    assert tags(db_path) == [
        ("r1", "cleanliness", "negative", "The room was dirty.", "keywords", "1"),
        ("r1", "location", "positive", "Great location.", "keywords", "1"),
    ]


def test_running_twice_is_idempotent(db_path, store):
    store.upsert_reviews([make_review(), make_review("r2", liked=None, disliked="Noisy street.")])
    classify_all(db_path)
    before = tags(db_path)

    second = classify_all(db_path)

    assert second == ClassifyResult(reviews_seen=2, reviews_classified=0, reviews_skipped=2, tags_written=0)
    assert tags(db_path) == before


def test_review_with_no_tags_is_remembered_as_done(db_path, store):
    store.upsert_reviews([make_review("blank", liked=None, disliked=None)])
    assert classify_all(db_path).reviews_classified == 1
    assert classify_all(db_path) == ClassifyResult(1, 0, 1, 0)
    assert tags(db_path) == []


def test_only_new_reviews_are_classified_on_later_runs(db_path, store):
    store.upsert_reviews([make_review("r1")])
    classify_all(db_path)
    store.upsert_reviews([make_review("r1"), make_review("r2")])

    result = classify_all(db_path)

    assert (result.reviews_seen, result.reviews_classified, result.reviews_skipped) == (2, 1, 1)


def test_changed_review_text_is_reclassified_and_old_tags_removed(db_path, store):
    store.upsert_reviews([make_review("r1", liked="Great location.", disliked="The room was dirty.")])
    classify_all(db_path)

    store.upsert_reviews([make_review("r1", liked="Friendly staff.", disliked=None)])
    result = classify_all(db_path)

    assert (result.reviews_classified, result.reviews_skipped) == (1, 0)
    assert [(t[1], t[2]) for t in tags(db_path, "r1")] == [("staff", "positive")]


def test_hotel_reply_changes_hash_and_triggers_harmless_reclassification(db_path, store):
    store.upsert_reviews([make_review("r1")])
    classify_all(db_path)
    before = tags(db_path)

    store.upsert_reviews([make_review("r1", host_reply="Sorry about that.")])
    result = classify_all(db_path)

    assert result.reviews_classified == 1
    assert tags(db_path) == before


def test_taxonomy_version_bump_reclassifies_everything(db_path, store, monkeypatch):
    store.upsert_reviews([make_review("r1"), make_review("r2", liked=None, disliked=None)])
    classify_all(db_path)

    monkeypatch.setattr(pipeline, "TAXONOMY_VERSION", "2")
    result = classify_all(db_path)

    assert (result.reviews_classified, result.reviews_skipped) == (2, 0)
    assert {t[5] for t in tags(db_path)} == {"2"}
    assert len(tags(db_path)) == 2  # replaced, not duplicated
    assert classify_all(db_path).reviews_skipped == 2


def test_missing_database_file_is_a_clear_error(tmp_path):
    with pytest.raises(FileNotFoundError):
        classify_all(str(tmp_path / "nope.db"))


def test_cli_prints_one_line_summary(db_path, store, capsys):
    store.upsert_reviews([make_review()])

    assert main(["--db", db_path]) == 0

    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 1
    assert "1 reviews seen" in out[0] and "2 tags written" in out[0]
