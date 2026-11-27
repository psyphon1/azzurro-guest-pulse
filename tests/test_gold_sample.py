import json
import sqlite3
from datetime import date

import pytest

from scraper.models import Review
from scraper.store import ReviewStore
from scripts.make_gold_sample import sample_reviews


def rv(key, slug, liked=None, disliked=None, lang="en", d=date(2026, 11, 1)):
    return Review(review_key=key, property=slug, rating=6.0, review_date=d, liked=liked, disliked=disliked, language=lang)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "g.db")
    store = ReviewStore(path)
    reviews = []
    for slug in ("olympic-paddington", "venus-potts-point-sydney", "chateau-de-venus"):
        for i in range(40):
            reviews.append(rv(f"{slug[:3]}{i:03d}", slug, liked=f"Great location number {i}", disliked=f"Noisy room {i}" if i % 2 else None))
    reviews += [
        rv("rating-only", "olympic-paddington"),                                             # no text
        rv("spanish", "olympic-paddington", liked="La habitacion era amplia y limpia", lang="es"),
        rv("pii", "olympic-paddington", liked="Call me on 0412 345 678 or mail jo.smith@example.com", lang="en"),
    ]
    store.upsert_reviews(reviews)
    return path


def test_sample_is_deterministic_for_a_seed_and_differs_for_another(db):
    a = sample_reviews(db, 30, seed=1)
    assert [r["id"] for r in a] == [r["id"] for r in sample_reviews(db, 30, seed=1)]
    assert [r["id"] for r in a] != [r["id"] for r in sample_reviews(db, 30, seed=2)]


def test_sample_is_spread_across_hotels(db):
    got = sample_reviews(db, 30, seed=1)
    per = {}
    for r in got:
        per[r["property"]] = per.get(r["property"], 0) + 1
    assert set(per) == {"olympic-paddington", "venus-potts-point-sydney", "chateau-de-venus"}
    assert all(9 <= n <= 11 for n in per.values())


def test_only_english_reviews_with_text_are_sampled(db):
    ids = {r["id"] for r in sample_reviews(db, 200, seed=1)}
    assert "rating-only" not in ids and "spanish" not in ids


def test_personal_contact_details_are_masked_before_anyone_reads_the_sample(db):
    text = json.dumps(sample_reviews(db, 200, seed=1))
    assert "jo.smith@example.com" not in text and "0412 345 678" not in text


def test_records_carry_no_reviewer_identity_and_no_classifier_output(db):
    rec = sample_reviews(db, 5, seed=1)[0]
    assert set(rec) == {"id", "property", "liked", "disliked"}          # no tags: the labeller must be blind


def test_asking_for_more_than_exist_returns_what_there_is(db):
    assert 100 < len(sample_reviews(db, 10_000, seed=1)) <= 121


def test_sampling_never_modifies_the_database(db):
    before = sqlite3.connect(db).execute("select count(*) from reviews").fetchone()
    sample_reviews(db, 30, seed=1)
    assert sqlite3.connect(db).execute("select count(*) from reviews").fetchone() == before


def test_the_sample_output_must_be_a_json_file_and_never_a_database(db, tmp_path, monkeypatch):
    import sys
    from scripts import make_gold_sample as m

    monkeypatch.setattr(sys, "argv", ["x", "--db", db, "--out", db])               # would overwrite the database
    with pytest.raises(SystemExit):
        m.main()
    assert sqlite3.connect(db).execute("select count(*) from reviews").fetchone()[0] > 100
