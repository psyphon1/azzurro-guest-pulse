"""Tests for insights.metrics. All data is built inside the tests; nothing reads data/*.db."""
from datetime import date, datetime, timezone

import pandas as pd
import pytest

from insights import metrics
from scraper.models import Review
from scraper.store import ReviewStore

P1, P2 = "olympic-paddington", "venus-surry-hills"


def mk(rows):
    """rows: (property, rating, 'YYYY-MM-DD'[, host_reply]) -> minimal reviews frame."""
    recs = []
    for i, r in enumerate(rows):
        recs.append({
            "review_key": f"r{i}", "property": r[0], "rating": r[1], "review_date": r[2],
            "host_reply": r[3] if len(r) > 3 else None,
        })
    return pd.DataFrame(recs)


# ---------------------------------------------------------------- bands / dates
def test_constants():
    assert (metrics.POSITIVE_FROM, metrics.NEGATIVE_BELOW, metrics.LOW_SAMPLE_BELOW) == (8.0, 5.0, 5)


@pytest.mark.parametrize("rating,band", [
    (10, "positive"), (8.0, "positive"), (7.9, "mixed"), (5.0, "mixed"), (4.9, "negative"), (1, "negative"),
])
def test_sentiment_band_boundaries(rating, band):
    assert metrics.sentiment_band(rating) == band


@pytest.mark.parametrize("bad", [None, float("nan")])
def test_sentiment_band_rejects_missing(bad):
    with pytest.raises(ValueError):
        metrics.sentiment_band(bad)


def test_week_start_of_monday_and_sunday():
    assert metrics.week_start_of(date(2026, 3, 2)) == date(2026, 3, 2)   # Monday
    assert metrics.week_start_of(date(2026, 3, 8)) == date(2026, 3, 2)   # Sunday still same week
    assert metrics.week_start_of(date(2026, 3, 9)) == date(2026, 3, 9)   # next Monday


def test_week_start_of_accepts_datetime_and_timestamp():
    assert metrics.week_start_of(datetime(2026, 3, 4, 23, 59)) == date(2026, 3, 2)
    assert metrics.week_start_of(pd.Timestamp("2026-03-04")) == date(2026, 3, 2)


def test_latest_complete_week_newest_review_on_sunday_is_not_yet_complete():
    # Newest review is Sunday 8 Mar: that day has only just begun in the data, so the last
    # fully elapsed week is the previous one (w/c 23 Feb).
    df = mk([(P1, 9, "2026-02-25"), (P1, 9, "2026-03-03"), (P1, 9, "2026-03-08")])
    assert metrics.latest_complete_week(df) == date(2026, 2, 23)


def test_latest_complete_week_newest_review_on_monday_itself():
    # A review on Monday 9 Mar belongs to the new, unfinished week.
    df = mk([(P1, 9, "2026-03-03"), (P1, 9, "2026-03-09")])
    assert metrics.latest_complete_week(df) == date(2026, 3, 2)


def test_latest_complete_week_with_today_after_sunday():
    df = mk([(P1, 9, "2026-03-03"), (P1, 9, "2026-03-08")])
    assert metrics.latest_complete_week(df, today=date(2026, 3, 9)) == date(2026, 3, 2)


def test_latest_complete_week_skips_empty_weeks_and_returns_week_with_data():
    df = mk([(P1, 9, "2026-02-10"), (P1, 9, "2026-03-09")])   # nothing in w/c 2 Mar or 23 Feb
    assert metrics.latest_complete_week(df) == date(2026, 2, 9)


def test_latest_complete_week_only_partial_week_falls_back_to_it():
    df = mk([(P1, 9, "2026-03-04")])
    assert metrics.latest_complete_week(df) == date(2026, 3, 2)


def test_latest_complete_week_empty_frame_is_none():
    assert metrics.latest_complete_week(mk([])) is None


# ---------------------------------------------------------------- loaders
def review(key, prop=P1, rating=9.0, day="2026-03-03", reply=None, **kw):
    return Review(review_key=key, property=prop, rating=rating, review_date=date.fromisoformat(day),
                  host_reply=reply, **kw)


@pytest.fixture
def db(tmp_path):
    path = str(tmp_path / "t.db")
    store = ReviewStore(path)
    store.upsert_reviews([
        review("a", P1, 9.0, "2026-03-03", reply="Thanks!"),   # Tuesday
        review("b", P2, 6.0, "2026-03-08"),                      # Sunday
        review("c", P1, 3.0, "2026-03-09"),                      # next Monday
        review("d", "unknown-slug", 8.0, "2026-03-09"),
    ])
    return path


def test_load_reviews_adds_derived_columns(db):
    df = metrics.load_reviews(db).set_index("review_key")
    assert pd.api.types.is_datetime64_any_dtype(df["review_date"])
    assert df.loc["a", "week_start"] == date(2026, 3, 2)
    assert df.loc["b", "week_start"] == date(2026, 3, 2)     # Sunday belongs to the Monday before
    assert df.loc["c", "week_start"] == date(2026, 3, 9)     # Monday starts a new week
    assert df.loc["a", "band"] == "positive"
    assert df.loc["b", "band"] == "mixed"
    assert df.loc["c", "band"] == "negative"
    assert bool(df.loc["a", "has_reply"]) is True
    assert bool(df.loc["b", "has_reply"]) is False
    assert df.loc["a", "property_name"] == "Olympic Hotel Paddington"
    assert df.loc["b", "property_name"] == "Central Sydney"
    assert df.loc["d", "property_name"] == "unknown-slug"    # unknown slug falls back to the slug


def test_load_reviews_blank_reply_counts_as_no_reply(tmp_path):
    path = str(tmp_path / "t.db")
    ReviewStore(path).upsert_reviews([review("a", reply="   ")])
    assert not metrics.load_reviews(path).loc[0, "has_reply"]


def test_load_reviews_empty_db_has_columns(tmp_path):
    path = str(tmp_path / "empty.db")
    ReviewStore(path)
    df = metrics.load_reviews(path)
    assert len(df) == 0
    for col in ("review_key", "review_date", "week_start", "band", "has_reply", "property_name"):
        assert col in df.columns


def test_load_reviews_does_not_create_missing_file(tmp_path):
    with pytest.raises(Exception):
        metrics.load_reviews(str(tmp_path / "nope.db"))
    assert not (tmp_path / "nope.db").exists()


def test_load_topics_missing_table_gives_empty_frame_with_columns(db):
    t = metrics.load_topics(db)
    assert len(t) == 0
    assert list(t.columns) == ["review_key", "topic", "polarity", "evidence", "method", "taxonomy_version"]


def test_load_topics_reads_rows(db):
    import sqlite3
    con = sqlite3.connect(db)
    con.execute("""CREATE TABLE review_topics (review_key TEXT NOT NULL, topic TEXT NOT NULL,
        polarity TEXT NOT NULL, evidence TEXT NOT NULL, method TEXT NOT NULL, taxonomy_version TEXT NOT NULL,
        PRIMARY KEY (review_key, topic, polarity))""")
    con.execute("INSERT INTO review_topics VALUES ('c','noise','negative','too loud','keywords','1')")
    con.commit()
    con.close()
    t = metrics.load_topics(db)
    assert len(t) == 1 and t.loc[0, "topic"] == "noise"


# ---------------------------------------------------------------- week summary / compare
W = date(2026, 3, 2)          # Monday
PREV = date(2026, 2, 23)


@pytest.fixture
def two_weeks():
    return mk([
        (P1, 9, "2026-02-23"), (P1, 7, "2026-02-26"),                 # prev week: avg 8.0
        (P1, 9, "2026-03-02"),                                        # Monday itself is in the week
        (P1, 4, "2026-03-08"),                                        # Sunday is in the week
        (P2, 6, "2026-03-04"),
        (P1, 10, "2026-03-09"),                                       # next Monday: NOT in the week
    ])


def test_week_summary_counts_and_average(two_weeks):
    s = metrics.week_summary(two_weeks, W)
    assert s.week_start == W
    assert s.n == 3
    assert s.avg_rating == pytest.approx((9 + 4 + 6) / 3)
    assert (s.positive, s.mixed, s.negative) == (1, 1, 1)


def test_week_summary_monday_and_sunday_boundaries():
    df = mk([(P1, 9, "2026-03-01"), (P1, 9, "2026-03-02"), (P1, 9, "2026-03-08"), (P1, 9, "2026-03-09")])
    assert metrics.week_summary(df, W).n == 2        # Sun 1 Mar and Mon 9 Mar are outside


def test_week_summary_empty_week_has_none_average(two_weeks):
    s = metrics.week_summary(two_weeks, date(2026, 1, 5))
    assert s.n == 0 and s.avg_rating is None
    assert (s.positive, s.mixed, s.negative) == (0, 0, 0)


def test_week_summary_empty_frame():
    s = metrics.week_summary(mk([]), W)
    assert s.n == 0 and s.avg_rating is None


def test_week_summary_property_filter(two_weeks):
    s = metrics.week_summary(two_weeks, W, properties=[P2])
    assert s.n == 1 and s.avg_rating == 6


def test_week_summary_accepts_non_monday_date(two_weeks):
    assert metrics.week_summary(two_weeks, date(2026, 3, 5)).week_start == W


def test_compare_weeks_delta(two_weeks):
    c = metrics.compare_weeks(two_weeks, W)
    assert c.current.week_start == W and c.previous.week_start == PREV
    assert c.previous.avg_rating == 8.0
    assert c.delta == pytest.approx(19 / 3 - 8.0)


def test_compare_weeks_delta_none_when_previous_week_empty():
    df = mk([(P1, 9, "2026-03-03")])
    c = metrics.compare_weeks(df, W)
    assert c.previous.n == 0 and c.delta is None


def test_compare_weeks_delta_none_when_current_week_empty():
    df = mk([(P1, 9, "2026-02-24")])
    assert metrics.compare_weeks(df, W).delta is None


# ---------------------------------------------------------------- breakdown / trend
def test_property_breakdown(two_weeks):
    b = metrics.property_breakdown(two_weeks, W).set_index("property")
    assert list(metrics.property_breakdown(two_weeks, W).columns) == [
        "property", "property_name", "avg_rating", "n", "prev_avg", "prev_n", "delta", "low_sample"]
    assert b.loc[P1, "n"] == 2 and b.loc[P1, "avg_rating"] == 6.5
    assert b.loc[P1, "prev_n"] == 2 and b.loc[P1, "prev_avg"] == 8.0
    assert b.loc[P1, "delta"] == pytest.approx(-1.5)
    assert bool(b.loc[P1, "low_sample"]) is True                  # 2 < 5
    assert b.loc[P2, "n"] == 1 and b.loc[P2, "prev_n"] == 0
    assert pd.isna(b.loc[P2, "prev_avg"]) and pd.isna(b.loc[P2, "delta"])


def test_property_breakdown_keeps_property_with_no_reviews_this_week():
    df = mk([(P1, 9, "2026-03-03"), (P2, 8, "2026-02-10")])
    b = metrics.property_breakdown(df, W).set_index("property")
    assert b.loc[P2, "n"] == 0 and pd.isna(b.loc[P2, "avg_rating"])


def test_property_breakdown_low_sample_flag_threshold():
    df = mk([(P1, 9, "2026-03-03")] * 5 + [(P2, 9, "2026-03-03")] * 4)
    b = metrics.property_breakdown(df, W).set_index("property")
    assert bool(b.loc[P1, "low_sample"]) is False and bool(b.loc[P2, "low_sample"]) is True


def test_property_breakdown_empty_frame():
    b = metrics.property_breakdown(mk([]), W)
    assert len(b) == 0 and "delta" in b.columns


def test_property_breakdown_single_property():
    b = metrics.property_breakdown(mk([(P1, 9, "2026-03-03")]), W)
    assert list(b["property"]) == [P1]


def test_weekly_trend_fills_empty_weeks(two_weeks):
    t = metrics.weekly_trend(two_weeks, date(2026, 2, 16), date(2026, 3, 9))
    assert list(t["week_start"]) == [date(2026, 2, 16), PREV, W, date(2026, 3, 9)]
    assert list(t["n"]) == [0, 2, 3, 1]
    assert pd.isna(t.loc[0, "avg_rating"]) and t.loc[1, "avg_rating"] == 8.0
    assert list(t.columns) == ["week_start", "n", "avg_rating", "positive", "mixed", "negative"]
    assert list(t["positive"]) == [0, 1, 1, 1]


def test_weekly_trend_property_filter_and_empty_frame(two_weeks):
    t = metrics.weekly_trend(two_weeks, PREV, W, properties=[P2])
    assert list(t["n"]) == [0, 1]
    e = metrics.weekly_trend(mk([]), PREV, W)
    assert list(e["n"]) == [0, 0] and e["avg_rating"].isna().all()


# ---------------------------------------------------------------- topics
def tp(rows):
    """rows: (review_key, topic, polarity)"""
    return pd.DataFrame(
        [{"review_key": k, "topic": t, "polarity": p, "evidence": "x", "method": "keywords",
          "taxonomy_version": "1"} for k, t, p in rows],
        columns=metrics.TOPIC_COLUMNS)


@pytest.fixture
def topic_world():
    # r0..r3 negative (rating 3), r4 mixed, r5 positive. Window = week of 2 Mar.
    df = mk([
        (P1, 3, "2026-03-02"), (P1, 3, "2026-03-03"), (P2, 2, "2026-03-04"), (P2, 4, "2026-03-08"),
        (P1, 6, "2026-03-04"), (P1, 9, "2026-03-05"),
        (P1, 3, "2026-02-24"),                                        # r6 previous week, negative
    ])
    t = tp([
        ("r0", "cleanliness", "negative"), ("r1", "cleanliness", "negative"),
        ("r1", "noise", "negative"), ("r2", "cleanliness", "negative"),
        ("r4", "noise", "negative"),                                  # mixed review: not in negative band
        ("r5", "cleanliness", "positive"),
        ("r6", "noise", "negative"),                                  # outside window
    ])
    return df, t


def test_topic_shares_negative(topic_world):
    df, t = topic_world
    s = metrics.topic_shares(df, t, W, date(2026, 3, 8)).set_index("topic")
    assert list(metrics.topic_shares(df, t, W, date(2026, 3, 8)).columns) == [
        "topic", "label", "count", "n_reviews", "share", "low_sample", "n_band_total"]
    assert s.loc["cleanliness", "count"] == 3 and s.loc["cleanliness", "n_reviews"] == 4
    assert s.loc["cleanliness", "share"] == pytest.approx(0.75)
    assert s.loc["noise", "count"] == 1                           # only r1; r4 is mixed, r6 out of window
    assert s.loc["cleanliness", "label"] == "Cleanliness"
    assert bool(s.loc["cleanliness", "low_sample"]) is True       # 4 < 5


def test_topic_shares_sorted_by_count_desc_then_topic(topic_world):
    df, t = topic_world
    s = metrics.topic_shares(df, t, W, date(2026, 3, 8))
    assert list(s["topic"]) == ["cleanliness", "noise"]


def test_topic_shares_positive_uses_positive_band(topic_world):
    df, t = topic_world
    s = metrics.topic_shares(df, t, W, date(2026, 3, 8), polarity="positive").set_index("topic")
    assert s.loc["cleanliness", "count"] == 1 and s.loc["cleanliness", "n_reviews"] == 1
    assert s.loc["cleanliness", "share"] == 1.0


def test_topic_shares_review_counted_once_per_topic():
    df = mk([(P1, 3, "2026-03-03")])
    t = tp([("r0", "noise", "negative")])
    t = pd.concat([t, t])                                          # duplicate tag rows
    s = metrics.topic_shares(df, t, W, date(2026, 3, 8))
    assert s.loc[0, "count"] == 1


def test_topic_shares_low_sample_false_at_five():
    df = mk([(P1, 3, "2026-03-03")] * 5)
    t = tp([(f"r{i}", "noise", "negative") for i in range(5)])
    s = metrics.topic_shares(df, t, W, date(2026, 3, 8))
    assert bool(s.loc[0, "low_sample"]) is False and s.loc[0, "n_reviews"] == 5


def test_topic_shares_property_filter(topic_world):
    df, t = topic_world
    s = metrics.topic_shares(df, t, W, date(2026, 3, 8), properties=[P2]).set_index("topic")
    assert s.loc["cleanliness", "count"] == 1 and s.loc["cleanliness", "n_reviews"] == 2
    assert "noise" not in s.index


def test_topic_shares_no_reviews_in_band_is_empty_not_division_by_zero():
    df = mk([(P1, 9, "2026-03-03")])                               # no negative reviews at all
    t = tp([("r0", "noise", "negative")])                          # stray tag on a positive review
    s = metrics.topic_shares(df, t, W, date(2026, 3, 8))
    assert len(s) == 0 and list(s.columns) == [
        "topic", "label", "count", "n_reviews", "share", "low_sample", "n_band_total"]


def test_topic_shares_empty_topics_and_empty_df(topic_world):
    df, _ = topic_world
    assert len(metrics.topic_shares(df, tp([]), W, date(2026, 3, 8))) == 0
    assert len(metrics.topic_shares(mk([]), tp([]), W, date(2026, 3, 8))) == 0
    assert len(metrics.topic_shares(df, None, W, date(2026, 3, 8))) == 0


def test_topic_shares_unknown_topic_id_uses_id_as_label():
    df = mk([(P1, 3, "2026-03-03")])
    s = metrics.topic_shares(df, tp([("r0", "parking", "negative")]), W, date(2026, 3, 8))
    assert s.loc[0, "label"] == "parking"


def test_topic_by_property_is_full_grid(topic_world):
    df, t = topic_world
    g = metrics.topic_by_property(df, t, W, date(2026, 3, 8))
    assert {"property_name", "topic", "label", "count"} <= set(g.columns)
    assert len(g) == 2 * 8                                         # 2 properties x 8 topics, zero-filled
    cell = g[(g["property"] == P1) & (g["topic"] == "cleanliness")]["count"].iloc[0]
    assert cell == 2
    assert g[(g["property"] == P2) & (g["topic"] == "location")]["count"].iloc[0] == 0


def test_topic_by_property_empty():
    g = metrics.topic_by_property(mk([]), tp([]), W, date(2026, 3, 8))
    assert len(g) == 0 and {"property_name", "topic", "label", "count"} <= set(g.columns)


# ---------------------------------------------------------------- unreplied
def test_unreplied_reviews_basic():
    df = mk([(P1, 3, "2026-03-03"), (P1, 9, "2026-03-04", "Thanks"), (P2, 6, "2026-03-05"),
             (P2, 2, "2026-03-06", "  ")])
    u = metrics.unreplied_reviews(df)
    assert sorted(u["review_key"]) == ["r0", "r2", "r3"]          # blank reply counts as unreplied
    assert list(u["review_date"]) == sorted(u["review_date"], reverse=True)   # newest first


def test_unreplied_reviews_property_and_band_filter():
    df = mk([(P1, 3, "2026-03-03"), (P2, 2, "2026-03-04"), (P2, 6, "2026-03-05")])
    assert list(metrics.unreplied_reviews(df, properties=[P2])["review_key"]) == ["r2", "r1"]
    assert list(metrics.unreplied_reviews(df, band="negative")["review_key"]) == ["r1", "r0"]


def test_unreplied_reviews_max_age_is_relative_to_newest_review():
    df = mk([(P1, 3, "2026-03-01"), (P1, 3, "2026-03-09"), (P1, 3, "2026-03-10")])
    assert list(metrics.unreplied_reviews(df, max_age_days=1)["review_key"]) == ["r2", "r1"]
    assert list(metrics.unreplied_reviews(df, max_age_days=1, as_of=date(2026, 3, 30))["review_key"]) == []


def test_unreplied_reviews_empty_frame():
    u = metrics.unreplied_reviews(mk([]))
    assert len(u) == 0 and "review_key" in u.columns


# ---------------------------------------------------------------- data_health
def _runs_db(tmp_path):
    path = str(tmp_path / "h.db")
    t = {"now": datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc)}
    store = ReviewStore(path, clock=lambda: t["now"])
    return path, store, t


NOW = datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)


def test_data_health_fresh_and_stale(tmp_path):
    path, store, t = _runs_db(tmp_path)
    store.upsert_reviews([review("a", P1), review("b", P1), review("c", P2)])
    t["now"] = datetime(2026, 3, 10, 6, 0, tzinfo=timezone.utc)       # 6h before NOW
    r = store.start_run(P1, "incremental"); store.finish_run(r, "ok", 1, 2, 0, 0, None)
    t["now"] = datetime(2026, 3, 8, 6, 0, tzinfo=timezone.utc)        # 54h before NOW
    r = store.start_run(P2, "incremental"); store.finish_run(r, "ok", 1, 1, 0, 0, None)
    h = metrics.data_health(path, now=NOW).set_index("property")
    assert list(metrics.data_health(path, now=NOW).columns) == [
        "property", "property_name", "stored", "last_ok_at", "latest_status", "latest_error", "stale",
        "truncated", "reported_total", "coverage_note"]
    assert h.loc[P1, "stored"] == 2 and h.loc[P2, "stored"] == 1
    assert bool(h.loc[P1, "stale"]) is False
    assert bool(h.loc[P2, "stale"]) is True
    assert h.loc[P1, "latest_status"] == "ok"


def test_data_health_exactly_48h_is_not_stale(tmp_path):
    path, store, t = _runs_db(tmp_path)
    t["now"] = datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)       # exactly 48h before NOW
    r = store.start_run(P1, "full"); store.finish_run(r, "ok", 1, 0, 0, 0, None)
    h = metrics.data_health(path, now=NOW).set_index("property")
    assert bool(h.loc[P1, "stale"]) is False


def test_data_health_latest_failure_but_old_success(tmp_path):
    path, store, t = _runs_db(tmp_path)
    t["now"] = datetime(2026, 3, 10, 0, 0, tzinfo=timezone.utc)
    r = store.start_run(P1, "full"); store.finish_run(r, "ok", 1, 0, 0, 0, None)
    t["now"] = datetime(2026, 3, 10, 11, 0, tzinfo=timezone.utc)
    r = store.start_run(P1, "full"); store.finish_run(r, "blocked", 0, 0, 0, 0, "captcha")
    h = metrics.data_health(path, now=NOW).set_index("property")
    assert h.loc[P1, "latest_status"] == "blocked" and h.loc[P1, "latest_error"] == "captcha"
    assert bool(h.loc[P1, "stale"]) is False                          # last OK run was 12h ago


def test_data_health_never_run_is_stale_and_all_configured_properties_listed(tmp_path):
    path, _, _ = _runs_db(tmp_path)
    h = metrics.data_health(path, now=NOW)
    assert len(h) == 4                                                # every configured property
    assert h["stale"].all() and h["last_ok_at"].isna().all()
    assert (h["stored"] == 0).all()


def test_data_health_default_now_is_current_utc(tmp_path):
    path, store, t = _runs_db(tmp_path)
    t["now"] = datetime.now(timezone.utc)
    r = store.start_run(P1, "full"); store.finish_run(r, "ok", 1, 0, 0, 0, None)
    h = metrics.data_health(path).set_index("property")
    assert bool(h.loc[P1, "stale"]) is False


def test_data_health_includes_unconfigured_property_slug(tmp_path):
    path, store, _ = _runs_db(tmp_path)
    store.upsert_reviews([review("z", "mystery")])
    h = metrics.data_health(path, now=NOW).set_index("property")
    assert h.loc["mystery", "stored"] == 1


# ---------------------------------------------------------------- generate_insights
import re


def build_world(cur_neg=15, cur_clean=6, prev_neg=10, prev_clean=2, cur_pos=25, prev_pos=22,
                prop_split=None, cur_nocomment=0, prev_nocomment=0):
    """Two weeks of reviews + topics. Negative reviews are rating 3, positive 9. Cleanliness tags on the
    first `*_clean` negative reviews of each week. Negatives alternate between P1 and P2 unless
    prop_split says otherwise."""
    rows, tags, k = [], [], 0

    def add(prop, rating, day, tag=None, reply=None, text=True):
        nonlocal k
        rows.append({"review_key": f"k{k}", "property": prop, "rating": rating, "review_date": day,
                     "host_reply": reply, "language": "en",
                     "liked": "nice" if text and rating >= 8 else None,
                     "disliked": "bad" if text and rating < 8 else None})
        if tag:
            tags.append((f"k{k}", tag, "negative"))
        k += 1

    for week_day, neg, clean, pos, nocomment in (
            ("2026-03-03", cur_neg, cur_clean, cur_pos, cur_nocomment),
            ("2026-02-24", prev_neg, prev_clean, prev_pos, prev_nocomment)):
        for i in range(nocomment):
            add(P1, 3, week_day, text=False)                      # rating-only negative review
        for i in range(neg):
            prop = (prop_split or (lambda i: P1 if i % 2 == 0 else P2))(i)
            add(prop, 3, week_day, "cleanliness" if i < clean else None)
        for i in range(pos):
            add(P1 if i % 2 == 0 else P2, 9, week_day, reply="Thanks")
    return pd.DataFrame(rows), tp(tags)


def pct_without_count(text):
    """True if some N% in text is not backed by a '(a of b)' count."""
    return len(re.findall(r"\d+%", text)) > len(re.findall(r"\(\d+ of \d+[;)]", text))


def test_insights_no_data_for_week_returns_single_info():
    df, t = build_world()
    ins = metrics.generate_insights(df, t, date(2026, 1, 5))
    assert len(ins) == 1 and ins[0].kind == "info" and ins[0].n == 0
    assert "No reviews" in ins[0].text and "5 Jan" in ins[0].text


def test_insights_empty_frame_returns_single_info():
    ins = metrics.generate_insights(mk([]), tp([]), W)
    assert len(ins) == 1 and ins[0].kind == "info"


def test_insights_top_negative_topic_sentence_with_counts():
    df, t = build_world()
    ins = metrics.generate_insights(df, t, W)
    topic = [i for i in ins if "of negative reviews" in i.text and "cleanliness" in i.text]
    assert len(topic) == 1
    text = topic[0].text
    assert "40% of negative reviews with a written comment this week mentioned cleanliness (6 of 15)" in text
    assert "up from 20% last week (2 of 10)" in text
    assert topic[0].kind == "alert" and topic[0].n == 15 and topic[0].property is None


def test_insights_topic_down_and_same_wording():
    df, t = build_world(cur_neg=10, cur_clean=2, prev_neg=10, prev_clean=6)
    text = next(i.text for i in metrics.generate_insights(df, t, W) if "of negative reviews" in i.text)
    assert "down from 60% last week (6 of 10)" in text
    df, t = build_world(cur_neg=10, cur_clean=3, prev_neg=10, prev_clean=3)
    text = next(i.text for i in metrics.generate_insights(df, t, W) if "of negative reviews" in i.text)
    assert "the same as 30% last week (3 of 10)" in text


def test_insights_topic_with_no_negative_reviews_last_week():
    df, t = build_world(prev_neg=0, prev_clean=0)
    text = next(i.text for i in metrics.generate_insights(df, t, W) if "of negative reviews" in i.text)
    assert "(6 of 15)" in text and "no negative reviews with a written comment last week" in text.lower()
    assert not pct_without_count(text)


def test_insights_topic_zero_last_week_shows_zero_count():
    df, t = build_world(prev_clean=0)
    text = next(i.text for i in metrics.generate_insights(df, t, W) if "of negative reviews" in i.text)
    assert "up from 0% last week (0 of 10)" in text


def test_insights_small_negative_sample_is_flagged():
    df, t = build_world(cur_neg=3, cur_clean=2, prev_neg=10, prev_clean=2)
    ins = metrics.generate_insights(df, t, W)
    topic = next(i for i in ins if "of negative reviews" in i.text)
    assert "(2 of 3)" in topic.text and "Only 3 negative reviews" in topic.text
    assert "treat with caution" in topic.text
    assert topic.kind == "info"                                   # too small to raise an alert


def test_insights_no_negative_reviews_is_good_news():
    df, t = build_world(cur_neg=0, cur_clean=0)
    ins = metrics.generate_insights(df, t, W)
    good = [i for i in ins if "No negative reviews" in i.text]
    assert len(good) == 1 and good[0].kind == "good" and "(0 of 25" in good[0].text or "0 of 25" in good[0].text


def test_insights_portfolio_score_drop():
    df, t = build_world(cur_neg=15, prev_neg=2, prev_clean=0, cur_pos=25, prev_pos=30)
    ins = metrics.generate_insights(df, t, W)
    p = next(i for i in ins if i.text.startswith("Average rating this week"))
    assert "40 reviews" in p.text and "down" in p.text and "last week (32 reviews)" in p.text
    assert p.kind == "alert" and p.n == 40


def test_insights_portfolio_score_rise_is_good():
    df, t = build_world(cur_neg=2, cur_clean=0, prev_neg=15, prev_clean=0, cur_pos=30, prev_pos=25)
    p = next(i for i in metrics.generate_insights(df, t, W) if i.text.startswith("Average rating this week"))
    assert "up" in p.text and p.kind == "good"


def test_insights_portfolio_flat_is_info():
    df, t = build_world(cur_neg=10, cur_clean=0, prev_neg=10, prev_clean=0, cur_pos=20, prev_pos=20)
    p = next(i for i in metrics.generate_insights(df, t, W) if i.text.startswith("Average rating this week"))
    assert p.kind == "info" and "level with last week" in p.text


def test_insights_no_previous_week_says_cannot_compare():
    df = mk([(P1, 9, "2026-03-03")] * 6)
    ins = metrics.generate_insights(df, tp([]), W)
    p = next(i for i in ins if i.text.startswith("Average rating this week"))
    assert "no reviews last week" in p.text.lower() and p.kind == "info"


def test_insights_small_sample_notice_comes_first():
    df = mk([(P1, 9, "2026-03-03"), (P1, 4, "2026-03-04"), (P1, 8, "2026-03-05")])
    ins = metrics.generate_insights(df, tp([]), W)
    assert "Only 3 reviews" in ins[0].text and "not enough" in ins[0].text.lower()
    assert ins[0].kind == "info" and ins[0].n == 3


def test_insights_no_small_sample_notice_when_enough_reviews():
    df, t = build_world()
    assert not any("not enough" in i.text.lower() for i in metrics.generate_insights(df, t, W))


def test_insights_biggest_property_movement():
    rows = ([(P1, 9, "2026-02-24")] * 6 + [(P1, 5, "2026-03-03")] * 6      # P1: 9.0 -> 5.0, n=6/6
            + [(P2, 8, "2026-02-24")] * 6 + [(P2, 8.5, "2026-03-03")] * 6)  # P2: +0.5
    ins = metrics.generate_insights(mk(rows), tp([]), W)
    m = [i for i in ins if i.property == P1 and "points" in i.text]
    assert len(m) == 1
    assert "Olympic Hotel Paddington dropped 4.0 points to 5.0" in m[0].text
    assert "(6 reviews)" in m[0].text and m[0].kind == "alert" and m[0].n == 6
    assert not any(i.property == P2 and "points" in i.text for i in ins)   # only the biggest mover


def test_insights_property_movement_small_sample_downgraded_and_flagged():
    rows = [(P1, 9, "2026-02-24")] * 6 + [(P1, 5, "2026-03-03")] * 2 + [(P2, 8, "2026-03-03")] * 6 \
        + [(P2, 8, "2026-02-24")] * 6
    m = next(i for i in metrics.generate_insights(mk(rows), tp([]), W) if i.property == P1)
    assert "2 reviews" in m.text and "treat with caution" in m.text and m.kind == "info"


def test_insights_no_property_movement_for_single_property():
    df = mk([(P1, 9, "2026-02-24")] * 6 + [(P1, 4, "2026-03-03")] * 6)
    ins = metrics.generate_insights(df, tp([]), W)
    assert not any(i.property for i in ins)


def test_insights_property_topic_spike():
    rows, tags = [], []
    for i in range(4):
        rows.append((P2, 3, "2026-03-03")); tags.append((f"r{len(rows) - 1}", "noise", "negative"))
    rows.append((P2, 3, "2026-02-24")); tags.append((f"r{len(rows) - 1}", "noise", "negative"))
    rows += [(P1, 9, "2026-03-03")] * 3
    ins = metrics.generate_insights(mk(rows), tp(tags), W)
    s = [i for i in ins if i.property == P2 and "noise" in i.text]
    assert len(s) == 1
    assert "Central Sydney: 4 negative reviews mentioned noise this week, up from 1 last week" in s[0].text
    assert s[0].kind == "alert" and s[0].n == 4


def test_insights_no_spike_for_small_increase():
    rows = [(P2, 3, "2026-03-03")] * 2 + [(P2, 3, "2026-02-24")] * 1 + [(P1, 9, "2026-03-03")] * 5
    tags = [("r0", "noise", "negative"), ("r1", "noise", "negative")]
    ins = metrics.generate_insights(mk(rows), tp(tags), W)
    assert not any(i.property == P2 and "this week, up from" in i.text for i in ins)


def test_insights_unreplied_negative_count():
    rows = [(P1, 3, "2026-03-03"), (P1, 2, "2026-03-04"), (P2, 4, "2026-02-20"),
            (P2, 3, "2026-03-04", "We are sorry"), (P1, 9, "2026-03-05"), (P1, 9, "2026-03-06"),
            (P1, 9, "2026-03-06"), (P1, 8, "2026-03-07")]
    ins = metrics.generate_insights(mk(rows), tp([]), W)
    u = next(i for i in ins if "no hotel reply" in i.text)
    assert u.text.startswith("3 negative reviews have no hotel reply yet")
    assert "2 of them from this week" in u.text and u.kind == "alert" and u.n == 3


def test_insights_unreplied_ignores_reviews_after_the_week_and_skips_when_zero():
    rows = [(P1, 3, "2026-03-10"), (P1, 9, "2026-03-03", "Thanks")] * 3
    ins = metrics.generate_insights(mk(rows), tp([]), W)
    assert not any("no hotel reply" in i.text for i in ins)


def test_insights_max_six_ranked_alerts_before_good_and_info():
    df, t = build_world(cur_neg=15, prev_neg=2, prev_clean=0, cur_pos=25, prev_pos=30)
    ins = metrics.generate_insights(df, t, W)
    assert 1 <= len(ins) <= 6
    rank = {"alert": 0, "good": 1, "info": 2}
    ranks = [rank[i.kind] for i in ins]
    assert ranks == sorted(ranks)


def test_insights_every_percentage_has_a_count_in_every_scenario():
    worlds = [build_world(), build_world(prev_neg=0, prev_clean=0), build_world(cur_neg=3, cur_clean=1),
              build_world(cur_neg=0, cur_clean=0), build_world(prev_clean=0), build_world(cur_clean=0)]
    for df, t in worlds:
        for i in metrics.generate_insights(df, t, W):
            assert not pct_without_count(i.text), i.text


def test_insights_work_without_topics():
    df, _ = build_world()
    for t in (None, tp([])):
        ins = metrics.generate_insights(df, t, W)
        assert ins and not any("mentioned" in i.text for i in ins)


def test_insights_deterministic_on_ties():
    df, t = build_world(cur_neg=4, cur_clean=2, prev_neg=4, prev_clean=2)
    t = pd.concat([t, tp([(f"k{i}", "noise", "negative") for i in range(2)])])  # noise ties cleanliness 2-2
    a = [i.text for i in metrics.generate_insights(df, t, W)]
    b = [i.text for i in metrics.generate_insights(df.sample(frac=1, random_state=1), t, W)]
    assert a == b
    assert any("mentioned cleanliness" in x for x in a)          # tie -> alphabetical topic id


# ---------------------------------------------------------------- written-comment denominator
def mk_text(rows):
    """rows: (property, rating, day, liked, disliked, language)"""
    return pd.DataFrame([{"review_key": f"r{i}", "property": r[0], "rating": r[1], "review_date": r[2],
                          "liked": r[3], "disliked": r[4], "language": r[5], "host_reply": None}
                         for i, r in enumerate(rows)])


@pytest.fixture
def text_world():
    # 4 negative reviews: r0,r1 with disliked text, r2 rating-only, r3 blank string. r4 negative with
    # only a *liked* text (still no complaint). r5 positive with liked text, r6 positive rating-only.
    df = mk_text([
        (P1, 3, "2026-03-03", None, "dirty room", "en"), (P1, 3, "2026-03-04", None, "noisy", "es"),
        (P1, 2, "2026-03-04", None, None, "en"), (P2, 4, "2026-03-05", None, "   ", "xu"),
        (P2, 3, "2026-03-05", "nice staff", None, "en"),
        (P1, 9, "2026-03-05", "great", None, "en"), (P1, 9, "2026-03-06", None, None, "en"),
    ])
    t = tp([("r0", "cleanliness", "negative"), ("r1", "noise", "negative"), ("r5", "staff", "positive")])
    return df, t


def test_topic_shares_denominator_is_reviews_with_written_comment(text_world):
    df, t = text_world
    s = metrics.topic_shares(df, t, W, date(2026, 3, 8))
    assert "n_band_total" in s.columns
    row = s.set_index("topic").loc["cleanliness"]
    assert (row["count"], row["n_reviews"], row["n_band_total"]) == (1, 2, 5)
    assert row["share"] == pytest.approx(0.5)
    assert bool(row["low_sample"]) is True


def test_topic_shares_positive_uses_liked_text(text_world):
    df, t = text_world
    row = metrics.topic_shares(df, t, W, date(2026, 3, 8), polarity="positive").iloc[0]
    assert (row["topic"], row["count"], row["n_reviews"], row["n_band_total"]) == ("staff", 1, 1, 2)


def test_topic_shares_low_sample_uses_comment_denominator():
    df = mk_text([(P1, 3, "2026-03-03", None, "bad", "en")] * 3 + [(P1, 3, "2026-03-03", None, None, "en")] * 6)
    t = tp([(f"r{i}", "noise", "negative") for i in range(3)])
    row = metrics.topic_shares(df, t, W, date(2026, 3, 8)).iloc[0]
    assert row["n_band_total"] == 9 and row["n_reviews"] == 3 and bool(row["low_sample"]) is True


def test_topic_shares_no_text_columns_means_every_review_counts():
    df = mk([(P1, 3, "2026-03-03")] * 2)                              # no liked/disliked columns at all
    s = metrics.topic_shares(df, tp([("r0", "noise", "negative")]), W, date(2026, 3, 8))
    assert s.loc[0, "n_reviews"] == 2 and s.loc[0, "n_band_total"] == 2


def test_comment_counts(text_world):
    df, _ = text_world
    c = metrics.comment_counts(df, W, date(2026, 3, 8))
    assert (c.n_band_total, c.n_with_comment, c.n_without_comment) == (5, 2, 3)
    assert c.n_non_english == 1                                       # the "es" review with a comment
    assert metrics.comment_counts(df, W, date(2026, 3, 8), polarity="positive").n_band_total == 2
    assert metrics.comment_counts(df, W, date(2026, 3, 8), properties=[P2]).n_band_total == 2


def test_comment_counts_non_english_codes_and_unknown_language():
    df = mk_text([(P1, 3, "2026-03-03", None, "x", lang) for lang in ("en", "en-GB", "xu", "xt", "zh", "ja", None)])
    assert metrics.comment_counts(df, W, date(2026, 3, 8)).n_non_english == 4    # xu xt zh ja; unknown is not counted


def test_comment_counts_empty():
    c = metrics.comment_counts(mk([]), W, date(2026, 3, 8))
    assert (c.n_band_total, c.n_with_comment, c.n_without_comment, c.n_non_english) == (0, 0, 0, 0)


def test_insight_topic_sentence_mentions_rating_only_reviews():
    df, t = build_world(cur_nocomment=4)
    text = next(i.text for i in metrics.generate_insights(df, t, W) if "of negative reviews" in i.text)
    assert ("40% of negative reviews with a written comment this week mentioned cleanliness "
            "(6 of 15; 4 other negative reviews had no comment)") in text
    assert "up from 20% last week (2 of 10)" in text
    assert not pct_without_count(text)


def test_insight_topic_sentence_singular_no_comment():
    df, t = build_world(cur_nocomment=1)
    text = next(i.text for i in metrics.generate_insights(df, t, W) if "of negative reviews" in i.text)
    assert "1 other negative review had no comment)" in text


def test_insight_negative_reviews_but_none_with_comment():
    df = mk_text([(P1, 3, "2026-03-03", None, None, "en")] * 6 + [(P1, 9, "2026-03-03", "ok", None, "en")] * 6)
    ins = metrics.generate_insights(df, tp([]), W)
    note = next(i for i in ins if "no written comment" in i.text)
    assert "6 negative reviews" in note.text and note.kind == "info"
    assert not any("mentioned" in i.text for i in ins)


def test_data_health_explains_a_page_capped_run_in_plain_words(tmp_path):
    path, store, t = _runs_db(tmp_path)
    store.upsert_reviews([review(f"k{i}", P1) for i in range(30)])
    t["now"] = datetime(2026, 3, 10, 6, 0, tzinfo=timezone.utc)
    r = store.start_run(P1, "full")
    store.finish_run(r, "ok", 3, 30, 0, 0, None, truncated=True, reported_total=3000, max_pages=3)

    h = metrics.data_health(path, now=NOW).set_index("property")

    assert bool(h.loc[P1, "truncated"]) is True
    assert h.loc[P1, "reported_total"] == 3000
    note = h.loc[P1, "coverage_note"]
    assert "30 of 3,000" in note and "newest" in note.lower() and "page limit" in note
    assert h.loc[P2, "coverage_note"] == ""          # untouched property: no note


def test_data_health_complete_run_has_no_coverage_note(tmp_path):
    path, store, t = _runs_db(tmp_path)
    store.upsert_reviews([review("a", P1)])
    r = store.start_run(P1, "full")
    store.finish_run(r, "ok", 1, 1, 0, 0, None, truncated=False, reported_total=1, max_pages=200)

    h = metrics.data_health(path, now=NOW).set_index("property")

    assert bool(h.loc[P1, "truncated"]) is False
    assert h.loc[P1, "coverage_note"] == ""


def test_data_health_works_on_a_database_from_before_the_page_cap_existed(tmp_path):
    import sqlite3
    path = str(tmp_path / "legacy.db")
    con = sqlite3.connect(path)
    con.executescript("""CREATE TABLE reviews (review_key TEXT PRIMARY KEY, property TEXT, rating REAL, review_date TEXT);
        CREATE TABLE scrape_runs (id INTEGER PRIMARY KEY, property TEXT, mode TEXT, started_at TEXT, finished_at TEXT,
            status TEXT, pages INTEGER, new INTEGER, updated INTEGER, rejected INTEGER, error TEXT);
        INSERT INTO scrape_runs VALUES (1,'olympic-paddington','full','2026-03-09T00:00:00+00:00','2026-03-09T00:01:00+00:00','ok',14,133,0,0,NULL);""")
    con.commit(); con.close()

    h = metrics.data_health(path, now=NOW).set_index("property")

    assert h.loc["olympic-paddington", "coverage_note"] == ""


def test_data_health_explains_a_date_window_run_in_plain_words(tmp_path):
    path, store, t = _runs_db(tmp_path)
    store.upsert_reviews([review(f"k{i}", P1) for i in range(40)])
    t["now"] = datetime(2026, 3, 10, 6, 0, tzinfo=timezone.utc)
    r = store.start_run(P1, "full")
    store.finish_run(r, "ok", 4, 40, 0, 0, None, truncated=True, reported_total=4305, max_pages=200,
                     stop_reason="date_window", since_days=365)

    h = metrics.data_health(path, now=NOW).set_index("property")

    note = h.loc[P1, "coverage_note"]
    assert "last 365 days" in note and "date window" in note
    assert "page limit" not in note                      # the real reason, not the secondary one
    assert bool(h.loc[P1, "truncated"]) is True


def test_data_health_page_cap_note_still_works_when_a_stop_reason_exists(tmp_path):
    path, store, t = _runs_db(tmp_path)
    store.upsert_reviews([review(f"k{i}", P1) for i in range(30)])
    r = store.start_run(P1, "full")
    store.finish_run(r, "ok", 3, 30, 0, 0, None, truncated=True, reported_total=3000, max_pages=3,
                     stop_reason="page_cap", since_days=None)

    note = metrics.data_health(path, now=NOW).set_index("property").loc[P1, "coverage_note"]

    assert "page limit" in note and "30 of 3,000" in note


def test_data_health_keeps_the_page_cap_note_on_a_database_that_has_no_stop_reason_column(tmp_path):
    import sqlite3
    path = str(tmp_path / "v1.db")
    con = sqlite3.connect(path)
    con.executescript("""CREATE TABLE reviews (review_key TEXT PRIMARY KEY, property TEXT, rating REAL, review_date TEXT);
        INSERT INTO reviews VALUES ('a','olympic-paddington',5,'2026-03-01'),('b','olympic-paddington',6,'2026-03-02');
        CREATE TABLE scrape_runs (id INTEGER PRIMARY KEY, property TEXT, mode TEXT, started_at TEXT, finished_at TEXT,
            status TEXT, pages INTEGER, new INTEGER, updated INTEGER, rejected INTEGER, error TEXT,
            truncated INTEGER, reported_total INTEGER, max_pages INTEGER);
        INSERT INTO scrape_runs VALUES (1,'olympic-paddington','full','2026-03-09T00:00:00+00:00','2026-03-09T00:01:00+00:00','ok',2,2,0,0,NULL,1,50,2);""")
    con.commit(); con.close()

    h = metrics.data_health(path, now=NOW).set_index("property")

    assert "page limit" in h.loc["olympic-paddington", "coverage_note"]


def test_data_health_explains_a_list_that_ended_early_in_plain_words(tmp_path):
    path, store, t = _runs_db(tmp_path)
    store.upsert_reviews([review(f"k{i}", P1) for i in range(30)])
    r = store.start_run(P1, "full")
    store.finish_run(r, "ok", 3, 30, 0, 0, None, truncated=True, reported_total=2386, stop_reason="ended_early")

    note = metrics.data_health(path, now=NOW).set_index("property").loc[P1, "coverage_note"]

    assert "30 of 2,386" in note and "ended early" in note.lower() and "older" in note.lower()
    assert "page limit" not in note and "date window" not in note
