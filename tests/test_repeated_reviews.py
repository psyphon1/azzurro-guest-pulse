import pandas as pd

from insights import metrics

COLS = ["property", "property_name", "rating", "n", "first_date", "last_date", "sample_text"]
P1, P2 = "venus-potts-point-sydney", "olympic-paddington"
TEXT = "I strongly advise against booking this hostel. My experience was shocking."


def reviews(rows):
    """rows: (property, rating, date, title, liked, disliked)"""
    return pd.DataFrame([{"review_key": f"k{i}", "property": r[0], "rating": r[1], "review_date": r[2],
                          "title": r[3], "liked": r[4], "disliked": r[5], "host_reply": None}
                         for i, r in enumerate(rows)])


def test_empty_input_returns_empty_frame_with_columns():
    for df in (pd.DataFrame(), reviews([])):
        out = metrics.repeated_reviews(df)
        assert list(out.columns) == COLS and len(out) == 0


def test_no_group_big_enough_returns_empty_frame():
    df = reviews([(P1, 1, "2024-10-25", None, None, TEXT)] * 4)
    out = metrics.repeated_reviews(df)
    assert list(out.columns) == COLS and out.empty


def test_group_of_identical_reviews_is_reported():
    rows = [(P1, 1, f"2024-10-{25 + i % 4}", None, None, TEXT) for i in range(6)]
    out = metrics.repeated_reviews(reviews(rows))
    assert len(out) == 1
    r = out.iloc[0]
    assert (r["property"], r["property_name"], r["rating"], r["n"]) == (P1, "Potts Point", 1, 6)
    assert str(r["first_date"])[:10] == "2024-10-25" and str(r["last_date"])[:10] == "2024-10-28"
    assert r["sample_text"].startswith("I strongly advise")


def test_text_is_normalised_for_case_and_whitespace():
    variants = [TEXT, TEXT.upper(), "  " + TEXT.replace(" ", "   ") + "\n", TEXT.replace(" ", "\n"), TEXT, TEXT]
    out = metrics.repeated_reviews(reviews([(P1, 1, "2024-10-25", None, None, v) for v in variants]))
    assert list(out["n"]) == [6]


def test_liked_and_disliked_together_form_the_text():
    rows = [(P1, 2, "2024-10-25", None, "Nice view", "Dirty")] * 5 + [(P1, 2, "2024-10-25", None, "Dirty", "Nice view")]
    out = metrics.repeated_reviews(reviews(rows))
    assert list(out["n"]) == [5]


def test_different_title_but_same_body_still_counts_as_repeated():
    rows = [(P1, 1, "2024-10-25", f"Title {i}", None, TEXT) for i in range(5)]
    assert list(metrics.repeated_reviews(reviews(rows))["n"]) == [5]


def test_title_only_reviews_group_on_the_title():
    rows = [(P1, 10, "2025-01-01", "10/10", None, None)] * 5
    assert list(metrics.repeated_reviews(reviews(rows))["n"]) == [5]


def test_different_rating_or_property_is_not_the_same_group():
    rows = ([(P1, 1, "2024-10-25", None, None, TEXT)] * 3 + [(P1, 2, "2024-10-25", None, None, TEXT)] * 3
            + [(P2, 1, "2024-10-25", None, None, TEXT)] * 3)
    assert metrics.repeated_reviews(reviews(rows)).empty
    assert list(metrics.repeated_reviews(reviews(rows), min_group=3)["n"]) == [3, 3, 3]


def test_blank_text_is_never_a_group():
    rows = [(P1, 8, "2025-01-01", None, None, None)] * 10 + [(P1, 8, "2025-01-01", "  ", " ", "\n")] * 10
    assert metrics.repeated_reviews(reviews(rows)).empty


def test_sorted_by_size_descending_and_min_group_respected():
    rows = ([(P1, 1, "2024-10-25", None, None, "aaa")] * 5 + [(P1, 1, "2024-10-26", None, None, "bbb")] * 8
            + [(P1, 1, "2024-10-27", None, None, "ccc")] * 6 + [(P1, 1, "2024-10-27", None, None, "ddd")] * 4)
    out = metrics.repeated_reviews(reviews(rows))
    assert list(out["n"]) == [8, 6, 5]
    assert list(metrics.repeated_reviews(reviews(rows), min_group=6)["n"]) == [8, 6]


def test_frame_without_text_columns_or_with_bad_values_does_not_raise():
    df = pd.DataFrame({"review_key": ["a", "b"], "property": [P1, P1], "rating": [1, 1],
                       "review_date": ["2024-10-25", "garbage"]})
    assert metrics.repeated_reviews(df).empty
    df = reviews([(P1, 1, "not a date", None, 5, float("nan"))] * 5)
    out = metrics.repeated_reviews(df)
    assert out.empty


def test_does_not_change_the_input_frame():
    df = reviews([(P1, 1, "2024-10-25", None, None, TEXT)] * 5)
    before = df.copy()
    metrics.repeated_reviews(df)
    pd.testing.assert_frame_equal(df, before)
