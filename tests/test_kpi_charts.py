"""Numbers behind the four KPI charts: topic impact, reply backlog, guest segments, safety by month."""
from datetime import date

import pandas as pd

import dashboard.ui.data as D


def _df(rows):
    df = pd.DataFrame(rows, columns=["review_key", "property", "rating", "review_date", "host_reply",
                                     "traveller_type", "room_type"])
    df["review_date"] = pd.to_datetime(df["review_date"])
    df["band"] = df["rating"].map(lambda r: "positive" if r >= 8 else "mixed" if r >= 5 else "negative")
    df["has_reply"] = df["host_reply"].notna()
    df["property_name"] = df["property"].map({"a": "Hotel A", "b": "Hotel B"})
    return df


ROWS = [
    ("r1", "a", 2, "2026-11-02", None, "Solo traveller", "Dorm"),
    ("r2", "a", 3, "2026-11-03", "Sorry", "Solo traveller", "Dorm"),
    ("r3", "a", 9, "2026-11-04", None, "Couple", "Private room"),
    ("r4", "b", 8, "2026-11-10", None, "Couple", "Private room"),
    ("r5", "b", 4, "2026-11-11", None, "Group", "Dorm"),
    ("r6", "b", 10, "2026-10-01", None, "Couple", "Private room"),
]
TOPICS = pd.DataFrame([
    ("r1", "cleanliness", "negative"), ("r2", "cleanliness", "negative"), ("r5", "noise", "negative"),
    ("r1", "safety", "negative"), ("r6", "safety", "negative"), ("r3", "location", "positive"),
], columns=["review_key", "topic", "polarity"])
LABELS = {"cleanliness": "Cleanliness", "noise": "Noise", "safety": "Safety & pests", "location": "Location"}


def test_topic_impact_compares_reviews_with_and_without_the_complaint():
    t = D.topic_impact(_df(ROWS), TOPICS, LABELS).set_index("topic")
    assert t.loc["cleanliness", "n"] == 2
    assert t.loc["cleanliness", "avg_with"] == 2.5                      # r1, r2
    assert t.loc["cleanliness", "avg_without"] == 7.8                   # r3..r6 = (9+8+4+10)/4 = 7.75
    assert t.loc["cleanliness", "delta"] == -5.2
    assert "location" not in t.index                                    # praise is not a cost
    assert list(D.topic_impact(_df(ROWS), TOPICS, LABELS)["topic"])[0] == "cleanliness"   # biggest cost first


def test_trend_bins_follow_the_period_length():
    unit, bins = D.trend_bins(date(2026, 11, 23), date(2026, 11, 28))           # this week so far: days
    assert unit == "day" and len(bins) == 6 and bins[0][2] == "Mon 23 Nov"
    unit, bins = D.trend_bins(date(2026, 10, 30), date(2026, 11, 28))           # 30 days: weeks, clipped
    assert unit == "week" and len(bins) == 5 and bins[0][0] == date(2026, 10, 30)
    unit, bins = D.trend_bins(date(2026, 9, 3), date(2026, 11, 28))             # custom ~3 months: weeks
    assert unit == "week" and bins[0][0] == date(2026, 9, 3) and bins[-1][1] == date(2026, 11, 28)
    unit, bins = D.trend_bins(date(2025, 11, 10), date(2026, 11, 28))           # all time: months, clipped
    assert unit == "month" and bins[0][0] == date(2025, 11, 10) and bins[-1] == (date(2026, 11, 1),
                                                                                date(2026, 11, 28), "Nov 2026")


def test_reply_trend_counts_negative_reviews_and_replies_inside_the_period_only():
    unit, w = D.reply_trend(_df(ROWS), date(2026, 11, 2), date(2026, 11, 15))
    assert unit == "day" and len(w) == 14 and w["negatives"].sum() == 3 and w["replied"].sum() == 1
    unit, w = D.reply_trend(_df(ROWS), date(2026, 9, 28), date(2026, 11, 15))
    w = w.set_index("start")
    first, second = w.loc[pd.Timestamp("2026-11-02")], w.loc[pd.Timestamp("2026-11-09")]
    assert unit == "week" and (first["negatives"], first["replied"], first["unreplied"]) == (2, 1, 1)
    assert first["rate"] == 50 and (second["negatives"], second["replied"]) == (1, 0)
    _, only_first_week = D.reply_trend(_df(ROWS), date(2026, 11, 2), date(2026, 11, 8))
    assert only_first_week["negatives"].sum() == 2


def test_reply_by_hotel():
    h = D.reply_by_hotel(_df(ROWS), date(2026, 11, 1), date(2026, 11, 30)).set_index("property_name")
    assert (h.loc["Hotel A", "negatives"], h.loc["Hotel A", "replied"], h.loc["Hotel A", "rate"]) == (2, 1, 50)
    assert h.loc["Hotel B", "rate"] == 0


def test_segment_scores_by_traveller_and_room_type():
    s = D.segment_scores(_df(ROWS), "traveller_type", min_n=1).set_index("segment")
    assert s.loc["Solo traveller", "n"] == 2 and s.loc["Solo traveller", "avg"] == 2.5
    assert s.loc["Solo traveller", "pct_negative"] == 100
    assert list(s.index)[0] == "Solo traveller"                         # least happy first
    assert D.segment_scores(_df(ROWS), "room_type", min_n=3).set_index("segment").index.tolist() == ["Dorm", "Private room"]
    assert D.segment_scores(_df(ROWS), "room_type", min_n=10).empty


def test_safety_trend_follows_the_period():
    unit, m = D.safety_trend(_df(ROWS), TOPICS, date(2026, 1, 1), date(2026, 11, 30))
    assert unit == "month" and m.loc["Nov 2026", "Hotel A"] == 1 and m.loc["Oct 2026", "Hotel B"] == 1
    unit, m = D.safety_trend(_df(ROWS), TOPICS, date(2026, 11, 1), date(2026, 11, 30))   # October left out
    assert unit == "week" and list(m.columns) == ["Hotel A"] and m.to_numpy().sum() == 1
    _, none = D.safety_trend(_df(ROWS), TOPICS, date(2026, 11, 20), date(2026, 11, 28))
    assert none.to_numpy().sum() == 0
