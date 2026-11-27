import sqlite3
from datetime import date

import pytest

from insights.topics import TAXONOMY_VERSION

from insights import pipeline
from insights.pipeline import ClassifyResult, classify_all, main
from scraper.models import Review
from scraper.store import ReviewStore


def make_review(key="r1", liked="Great location.", disliked="The room was dirty.", language="en", **kw):
    return Review(review_key=key, property="olympic-paddington", rating=6.0,
                  review_date=date(2026, 11, 20), liked=liked, disliked=disliked, language=language, **kw)


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
        ("r1", "cleanliness", "negative", "The room was dirty.", "keywords", TAXONOMY_VERSION),
        ("r1", "location", "positive", "Great location.", "keywords", TAXONOMY_VERSION),
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

    monkeypatch.setattr(pipeline, "TAXONOMY_VERSION", "99")
    result = classify_all(db_path)

    assert (result.reviews_classified, result.reviews_skipped) == (2, 0)
    assert {t[5] for t in tags(db_path)} == {"99"}
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


# ---------------------------------------------------------------- language gate
FRENCH = "La chambre etait sale et le wifi ne marchait pas, la location est loin de tout."


JAPANESE = "部屋が汚くて、wifiも使えなかった。location"


def test_french_review_is_tagged_with_the_french_keywords(db_path, store):
    store.upsert_reviews([make_review("fr1", liked=None, disliked=FRENCH, language="fr"), make_review("en1")])

    first = classify_all(db_path)

    assert first.reviews_classified == 2
    got = {(t[1], t[2]) for t in tags(db_path, "fr1")}
    assert ("cleanliness", "negative") in got and ("facilities", "negative") in got
    assert ("location", "negative") not in got            # "location" means renting in French: not a keyword there
    assert [t[1] for t in tags(db_path, "en1")] == ["cleanliness", "location"]
    assert classify_all(db_path) == ClassifyResult(2, 0, 2, 0)          # not re-run


def test_unsupported_language_gets_no_tags_and_is_remembered(db_path, store):
    store.upsert_reviews([make_review("ja1", liked=None, disliked=JAPANESE, language="ja")])
    assert classify_all(db_path).reviews_classified == 1
    assert tags(db_path, "ja1") == []
    assert classify_all(db_path).reviews_skipped == 1


def test_xu_english_text_is_tagged_but_xt_chinese_is_not(db_path, store):
    store.upsert_reviews([
        make_review("xu1", liked="The location is perfect.", disliked=None, language="xu"),
        make_review("xt1", liked=None, disliked="房間很髒，而且有wifi問題 location", language="xt"),
    ])
    classify_all(db_path)
    assert [t[1] for t in tags(db_path, "xu1")] == ["location"]
    assert tags(db_path, "xt1") == []


def test_missing_language_is_judged_by_text(db_path, store):
    store.upsert_reviews([
        make_review("n1", liked=None, disliked="The room was dirty and the street was noisy.", language=None),
        make_review("n2", liked=None, disliked=FRENCH, language=None),
    ])
    classify_all(db_path)
    assert [t[1] for t in tags(db_path, "n1")] == ["cleanliness", "noise"]
    assert tags(db_path, "n2") == []


def test_classifier_revision_bump_removes_tags_given_to_unsupported_languages(db_path, store, monkeypatch):
    store.upsert_reviews([make_review("fr1", liked=None, disliked=JAPANESE, language="ja")])
    # Simulate the old behaviour: a tag written under the previous classifier revision.
    real = pipeline.classify_review
    monkeypatch.setattr(pipeline, "classify_review", lambda liked, disliked, language=None: real("Great location.", None))
    monkeypatch.setattr(pipeline, "CLASSIFIER_REVISION", "old")
    monkeypatch.setattr(pipeline, "analysis_language", lambda *a: "en")
    classify_all(db_path)
    assert len(tags(db_path, "fr1")) == 1

    monkeypatch.undo()
    result = classify_all(db_path)

    assert result.reviews_classified == 1
    assert tags(db_path, "fr1") == []


def test_classifier_revision_is_bumped_for_the_language_gate():
    from insights.classify import CLASSIFIER_REVISION
    assert int(CLASSIFIER_REVISION) >= 4


def test_pipeline_accepts_another_classifier_and_records_its_method(db_path, store):
    from insights.classify import TopicTag

    class Fixed:
        method = "other"

        def classify(self, liked, disliked, language):
            return [TopicTag("noise", "negative", "x", self.method)]

    store.upsert_reviews([make_review("o1")])
    classify_all(db_path, classifier=Fixed())
    assert {(t[1], t[4]) for t in tags(db_path, "o1")} == {("noise", "other")}
