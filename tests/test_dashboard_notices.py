"""Plain-language notices on the dashboard: reviews that are not in English (item 3), repeated reviews (item 4).

Synthetic data in tmp_path only; today is frozen so the default view is the week of Mon 16 Nov 2026.
"""
from datetime import date, datetime, timezone

import pytest
from streamlit.testing.v1 import AppTest

import dashboard.ui.data as D
from insights import metrics
from insights.pipeline import classify_all
from scraper.config import PROPERTIES
from scraper.models import Review
from scraper.store import ReviewStore
from tests.test_dashboard_smoke import APP, page_text

HOTEL = PROPERTIES[0].slug
TODAY = date(2026, 11, 25)
EN_BAD = "The room was dirty and the bathroom smelled."
FR_BAD = "La chambre etait sale et la salle de bain sentait mauvais."


def build(path, specs):
    """specs: dicts with rating, day, language, liked, disliked, (slug)."""
    store = ReviewStore(str(path), clock=lambda: datetime(2026, 11, 25, 8, 0, tzinfo=timezone.utc))
    by_slug: dict[str, list[Review]] = {}
    for i, sp in enumerate(specs):
        slug = sp.get("slug", HOTEL)
        by_slug.setdefault(slug, []).append(Review(
            review_key=f"nt-{slug}-{i}", property=slug, rating=sp["rating"], review_date=sp["day"],
            title=None, liked=sp.get("liked"), disliked=sp.get("disliked"), language=sp.get("language", "en")))
    for slug, reviews in by_slug.items():
        res = store.upsert_reviews(reviews)
        run = store.start_run(slug, "full")
        store.finish_run(run, "ok", pages=1, new=res.new, updated=0, rejected=0, error=None)
    store.close()
    classify_all(str(path))
    return path


def run(monkeypatch, db):
    monkeypatch.setattr(D, "today_sydney", lambda: TODAY)
    monkeypatch.setenv("REVIEWS_DB", str(db))
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    return at


WEEK = date(2026, 11, 18)      # inside the default view: the week of Mon 16 Nov


def mixed_language_specs():
    specs = [dict(rating=3.0, day=WEEK, language="en", disliked=EN_BAD) for _ in range(3)]
    specs += [dict(rating=3.0, day=WEEK, language="fr", disliked=FR_BAD) for _ in range(2)]
    specs += [dict(rating=3.0, day=WEEK, language="en")]                            # rating only: not counted
    specs += [dict(rating=9.0, day=WEEK, language="en", liked="Great location and friendly staff.")]
    specs += [dict(rating=9.0, day=WEEK, language="de", liked="Tolle Lage und freundliches Personal.")]
    return specs


# ------------------------------------------------------------------------------ non-English disclosure
def test_topics_section_says_how_many_reviews_are_not_in_english(monkeypatch, tmp_path):
    at = run(monkeypatch, build(tmp_path / "reviews.db", mixed_language_specs()))
    text = page_text(at)
    assert ("2 of 5 negative reviews with a comment in this period are not in English, "
            "so they are left out of these topic counts.") in text


def test_the_numbers_match_the_topic_table_and_the_metric(monkeypatch, tmp_path):
    db = build(tmp_path / "reviews.db", mixed_language_specs())
    at = run(monkeypatch, db)
    df = metrics.load_reviews(str(db))
    cc = metrics.comment_counts(df, date(2026, 11, 16), date(2026, 11, 22), "negative")
    shares = metrics.topic_shares(df, metrics.load_topics(str(db)), date(2026, 11, 16), date(2026, 11, 22), "negative")
    assert cc.n_with_comment == int(shares["n_reviews"].iloc[0]) == 5      # same denominator as the topic chart
    assert getattr(cc, "n_non_english", 0) == 2
    assert f"{cc.n_non_english} of {cc.n_with_comment} negative reviews with a comment" in page_text(at)


def test_praise_view_uses_the_praise_counts(monkeypatch, tmp_path):
    at = run(monkeypatch, build(tmp_path / "reviews.db", mixed_language_specs()))
    at.radio(key="topic_view").set_value("Praise").run()
    assert not at.exception, [e.value for e in at.exception]
    text = page_text(at)
    assert "1 of 2 positive reviews with a comment in this period is not in English" in text
    assert "of 5 negative reviews with a comment in this period are not in English" not in text


def test_no_sentence_when_every_review_is_english(monkeypatch, tmp_path):
    specs = [dict(rating=3.0, day=WEEK, disliked=EN_BAD) for _ in range(3)]
    text = page_text(run(monkeypatch, build(tmp_path / "reviews.db", specs)))
    assert "are not in English" not in text and "is not in English" not in text


def test_singular_wording(monkeypatch, tmp_path):
    specs = [dict(rating=3.0, day=WEEK, disliked=EN_BAD), dict(rating=3.0, day=WEEK, language="fr", disliked=FR_BAD)]
    text = page_text(run(monkeypatch, build(tmp_path / "reviews.db", specs)))
    assert "1 of 2 negative reviews with a comment in this period is not in English, so it is left out of these topic counts." in text


def test_how_to_read_says_tags_are_only_given_to_english_reviews(monkeypatch, tmp_path):
    text = page_text(run(monkeypatch, build(tmp_path / "reviews.db", mixed_language_specs())))
    assert "Topic tags are only given to reviews written in English" in text


# ------------------------------------------------------------------------------ repeated reviews
POTTS = PROPERTIES[1].slug
POTTS_NAME = PROPERTIES[1].name
CAMPAIGN = "I strongly advise against booking this hostel. It was a terrible experience."


def repeat_specs(n=6, text=CAMPAIGN, rating=1.0, slug=POTTS, start=date(2024, 10, 25), spread=3):
    from datetime import timedelta
    return [dict(rating=rating, day=start + timedelta(days=i % spread), slug=slug, disliked=text) for i in range(n)]


def recent_specs():
    return [dict(rating=7.0, day=WEEK, slug=HOTEL, liked=f"Lovely stay number {i}.") for i in range(3)]


def notices(at):
    return [e.value for e in at.markdown if "Repeated reviews:" in e.value]


def test_repeated_reviews_notice_names_hotel_count_and_months(monkeypatch, tmp_path):
    at = run(monkeypatch, build(tmp_path / "reviews.db", recent_specs() + repeat_specs()))
    found = notices(at)
    assert len(found) == 1
    assert (f"Repeated reviews: 6 reviews at {POTTS_NAME} share the same score and text (Oct 2024). "
            "They are included in every number on this page; read them in the feed before drawing conclusions.") in found[0]
    assert "terrible experience" in found[0]          # a sample of the text, so staff can search the feed for it


def test_months_span_when_the_group_crosses_months(monkeypatch, tmp_path):
    from datetime import timedelta
    specs = [dict(rating=1.0, day=date(2024, 10, 28) + timedelta(days=i * 3), slug=POTTS, disliked=CAMPAIGN) for i in range(6)]
    found = notices(run(monkeypatch, build(tmp_path / "reviews.db", recent_specs() + specs)))
    assert "(Oct 2024 to Nov 2024)" in found[0]


def test_at_most_three_groups_largest_first(monkeypatch, tmp_path):
    specs = recent_specs()
    for k, n in enumerate([5, 9, 7, 6]):
        specs += repeat_specs(n=n, text=f"Copied text number {k} about the very same stay.")
    found = notices(run(monkeypatch, build(tmp_path / "reviews.db", specs)))
    assert len(found) == 3
    assert [f.split("Repeated reviews: ")[1].split(" ")[0] for f in found] == ["9", "7", "6"]


def test_no_notice_without_repeats(monkeypatch, tmp_path):
    text = page_text(run(monkeypatch, build(tmp_path / "reviews.db", recent_specs() + repeat_specs(n=4))))
    assert "Repeated reviews" not in text


def test_sample_text_is_escaped_masked_and_cut(monkeypatch, tmp_path):
    hostile = "<script>alert(1)</script> write to guest@example.com or 0412 345 678 " + "x" * 200
    found = notices(run(monkeypatch, build(tmp_path / "reviews.db", recent_specs() + repeat_specs(text=hostile))))
    blob = found[0]
    assert "<script" not in blob and "&lt;script&gt;" in blob
    assert "guest@example.com" not in blob and "0412 345 678" not in blob
    assert "x" * 81 not in blob


def test_notice_survives_a_metrics_module_without_the_function(monkeypatch, tmp_path):
    db = build(tmp_path / "reviews.db", recent_specs() + repeat_specs())
    monkeypatch.delattr(metrics, "repeated_reviews")
    at = run(monkeypatch, db)
    assert "Repeated reviews" not in page_text(at)


def test_notice_is_shown_even_when_the_chosen_period_is_empty(monkeypatch, tmp_path):
    at = run(monkeypatch, build(tmp_path / "reviews.db", recent_specs() + repeat_specs()))
    at.sidebar.selectbox(key="range_preset").select("This week so far").run()
    assert "No reviews between" in page_text(at)
    assert len(notices(at)) == 1
