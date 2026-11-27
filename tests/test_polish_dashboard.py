"""Pure logic behind the polished dashboard: periods, URL filters, KPIs, sparkline, presets, profanity."""
from datetime import date

import pandas as pd
import pytest

import dashboard.ui.data as D
from dashboard.ui.privacy import mask_profanity

TODAY = date(2026, 11, 27)          # a Friday


def test_default_period_is_the_current_week_so_far():
    assert D.DEFAULT_PERIOD == "This week"
    assert D.period_range("This week", TODAY, date(2025, 1, 1), TODAY) == (date(2026, 11, 23), TODAY, date(2026, 11, 23))
    assert D.period_label("This week", date(2026, 11, 23), TODAY, TODAY) == "This week so far, Mon 23 Nov to today"


def test_last_week_and_30_days_and_custom():
    assert D.period_range("Last week", TODAY, date(2025, 1, 1), TODAY)[:2] == (date(2026, 11, 16), date(2026, 11, 22))
    assert D.period_range("Last 30 days", TODAY, date(2025, 1, 1), TODAY)[:2] == (date(2026, 10, 29), TODAY)
    s, e, _ = D.period_range("Custom", TODAY, date(2025, 1, 1), TODAY, (date(2026, 3, 9), date(2026, 3, 1)))
    assert (s, e) == (date(2026, 3, 1), date(2026, 3, 9))


def test_previous_range_has_the_same_length():
    assert D.previous_range(date(2026, 11, 23), date(2026, 11, 27)) == (date(2026, 11, 18), date(2026, 11, 22))


@pytest.mark.parametrize("params,expected", [
    ({}, ("This week", None, None)),
    ({"period": "Last week", "hotels": "a,b,zzz"}, ("Last week", ["a", "b"], None)),
    ({"period": "<script>", "hotels": "zzz"}, ("This week", None, None)),
    ({"period": "Custom", "from": "2026-03-01", "to": "2026-03-09"},
     ("Custom", None, (date(2026, 3, 1), date(2026, 3, 9)))),
    ({"period": "Custom", "from": "garbage", "to": "2026-03-09"}, ("Custom", None, None)),
])
def test_url_filters_are_validated(params, expected):
    assert D.parse_query(params, ["a", "b", "c"]) == expected


def test_to_query_round_trip():
    q = D.to_query("Custom", ["a"], ["a", "b"], (date(2026, 3, 1), date(2026, 3, 9)))
    assert D.parse_query(q, ["a", "b"]) == ("Custom", ["a"], (date(2026, 3, 1), date(2026, 3, 9)))
    assert "hotels" not in D.to_query("This week", ["a", "b"], ["a", "b"], None)


def _df(rows):
    df = pd.DataFrame(rows, columns=["review_key", "property", "rating", "review_date", "host_reply"])
    df["review_date"] = pd.to_datetime(df["review_date"])
    df["band"] = df["rating"].map(lambda r: "positive" if r >= 8 else "mixed" if r >= 5 else "negative")
    df["has_reply"] = df["host_reply"].notna()
    return df


def test_kpis_compare_with_the_previous_window():
    df = _df([("a", "p", 9, "2026-11-24", None), ("b", "p", 3, "2026-11-25", None), ("c", "p", 7, "2026-11-19", "ok")])
    avg, n, neg, unanswered = D.kpis(df, date(2026, 11, 23), TODAY, TODAY)
    assert (avg.value, avg.delta, avg.tone) == ("6.0", -1.0, "bad")
    assert (n.value, n.delta_text) == ("2", "Up 1 vs previous")
    assert (neg.value, neg.tone) == ("50%", "bad") and "1 of 2" in neg.caption
    assert unanswered.value == "1" and avg.small


def test_kpis_with_no_reviews_do_not_crash():
    out = D.kpis(_df([]), date(2026, 11, 23), TODAY, TODAY)
    assert out[0].value == "–" and out[0].delta_text == "No comparison"


def test_sparkline():
    assert D.sparkline([1, 10, None]) == "▁█·"


def test_presets_from_worth_a_look_are_validated():
    assert D.apply_preset({"neg": True, "noreply": True}, {"noise"}, {"p"}) == (["Negative", "Needs reply"], "", None)
    assert D.apply_preset({"safety": True, "topic": "negative:noise", "property": "p"}, {"noise"}, {"p"}) == \
        (["Safety"], "negative:noise", "p")
    assert D.apply_preset({"topic": "negative:<b>", "property": "evil", "neg": "yes"}, {"noise"}, {"p"}) == ([], "", None)
    assert D.apply_preset("garbage", set(), set()) == ([], "", None)


@pytest.mark.parametrize("text,expected", [
    ("This shitty place", "This s***** place"), ("Fucking noisy", "F****** noisy"),
    ("Scunthorpe is fine", "Scunthorpe is fine"), ("c'est la merde", "c'est la m****"), (None, None),
])
def test_profanity_mask(text, expected):
    assert mask_profanity(text) == expected
