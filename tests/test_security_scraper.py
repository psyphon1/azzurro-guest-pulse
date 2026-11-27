"""Security regression tests for the COLLECTION side (scraper/*). Each test is named for the attack.

Rules of engagement: local fixtures and tmp_path databases only. No network, no real browser,
never data/*.db. See docs/security/scraper.md for the findings table.
"""
import copy
import json
import math
import sqlite3

import pytest

from scraper.models import ParsedPage, RejectedReview, Review
from scraper.parse import ParseError, parse_page
from scraper.store import ReviewStore

SLUG = "olympic-paddington"


def payload_with(raw_payload, mutate):
    """Deep copy of the fixture with the first card mutated by ``mutate(card)``."""
    p = copy.deepcopy(raw_payload)
    mutate(p["data"]["reviewListFrontend"]["reviewCard"][0])
    return p


def first_result(raw_payload, mutate):
    page = parse_page(payload_with(raw_payload, mutate), SLUG)
    return page


# =====================================================================================
# S01  Poisoned response: wrong types must quarantine ONE card, never crash the run
# =====================================================================================
@pytest.mark.parametrize("junk", [[], ["x"], "a string", 12, 1.5, None, True])
def test_card_of_wrong_type_is_quarantined_not_a_crash(raw_payload, junk):
    p = copy.deepcopy(raw_payload)
    p["data"]["reviewListFrontend"]["reviewCard"].insert(0, junk)

    page = parse_page(p, SLUG)

    assert len(page.reviews) == 5          # the five honest cards survive
    assert len(page.rejected) == 1


@pytest.mark.parametrize("section", ["textDetails", "guestDetails", "bookingDetails", "partnerReply"])
@pytest.mark.parametrize("junk", [[], ["x"], "str", 7])
def test_nested_section_of_wrong_type_is_quarantined_not_a_crash(raw_payload, section, junk):
    page = first_result(raw_payload, lambda c: c.__setitem__(section, junk))

    assert len(page.reviews) + len(page.rejected) == 5


def test_room_type_of_wrong_type_is_quarantined_not_a_crash(raw_payload):
    page = first_result(raw_payload, lambda c: c["bookingDetails"].__setitem__("roomType", ["x"]))
    assert len(page.reviews) + len(page.rejected) == 5


@pytest.mark.parametrize("field,value", [
    ("reviewUrl", 12345), ("reviewUrl", ["a"]), ("reviewUrl", None), ("reviewUrl", {"a": 1}),
    ("reviewScore", "high"), ("reviewScore", None), ("reviewScore", [5]), ("reviewScore", {}),
    ("reviewedDate", "yesterday"), ("reviewedDate", None), ("reviewedDate", [1]),
])
def test_wrong_type_in_required_field_is_quarantined_with_a_safe_key(raw_payload, field, value):
    page = first_result(raw_payload, lambda c: c.__setitem__(field, value))

    assert len(page.rejected) == 1
    key = page.rejected[0].review_key
    assert key is None or (isinstance(key, str) and len(key) <= 128)


def test_none_everywhere_is_quarantined(raw_payload):
    def blank(card):
        for k in list(card):
            card[k] = None
    page = first_result(raw_payload, blank)
    assert len(page.rejected) == 1


@pytest.mark.parametrize("bad_filter", [5, "ALL", {"value": "ALL", "count": 3}, [None], [5], ["ALL"], [[]]])
def test_reported_total_with_malformed_filter_does_not_crash(raw_payload, bad_filter):
    p = copy.deepcopy(raw_payload)
    p["data"]["reviewListFrontend"]["reviewScoreFilter"] = bad_filter

    page = parse_page(p, SLUG)

    assert page.reported_total is None
    assert len(page.reviews) == 5


@pytest.mark.parametrize("count", ["133", -5, 10**12, 1e30, float("nan"), True, None, [1], {"a": 1}, 3.5])
def test_reported_total_must_be_a_sane_non_negative_integer(raw_payload, count):
    p = copy.deepcopy(raw_payload)
    p["data"]["reviewListFrontend"]["reviewScoreFilter"] = [{"value": "ALL", "count": count}]

    page = parse_page(p, SLUG)

    assert page.reported_total is None


@pytest.mark.parametrize("payload", [None, [], "x", 5, {"data": None}, {"data": []}, {"data": {"reviewListFrontend": []}},
                                     {"data": {"reviewListFrontend": "x"}}, {"data": {"reviewListFrontend": {"reviewCard": {}}}}])
def test_top_level_garbage_raises_parse_error_only(payload):
    with pytest.raises(ParseError):
        parse_page(payload, SLUG)


# =====================================================================================
# S02  Poisoned values: timestamps, ratings, nights, dates, votes
# =====================================================================================
@pytest.mark.parametrize("ts", [
    10**30, -10**30, 10**18, -(10**12), 253402300800, 253402300799, -62135596801, 2**63, 2**63 - 1,
    float("nan"), float("inf"), float("-inf"), 1e300, True,
])
def test_absurd_unix_timestamp_is_quarantined_not_an_overflow_crash(raw_payload, ts):
    page = first_result(raw_payload, lambda c: c.__setitem__("reviewedDate", ts))

    assert len(page.rejected) == 1 and len(page.reviews) == 4


@pytest.mark.parametrize("ts,why", [
    (-2208988800, "year 1900"),
    (253402214400, "year 9999"),
    (4102444800, "year 2100, in the future"),
    (0, "1970 epoch default: a missing date coerced to zero"),
])
def test_review_date_outside_plausible_window_is_quarantined(raw_payload, ts, why):
    page = first_result(raw_payload, lambda c: c.__setitem__("reviewedDate", ts))

    assert len(page.rejected) == 1, why


@pytest.mark.parametrize("score", [float("nan"), float("inf"), float("-inf"), 0, 0.99, 10.01, -1, 1e308, True, False, "NaN", "Infinity"])
def test_nonsense_rating_is_quarantined(raw_payload, score):
    page = first_result(raw_payload, lambda c: c.__setitem__("reviewScore", score))

    assert len(page.rejected) == 1 and len(page.reviews) == 4


@pytest.mark.parametrize("nights", [-1, -(10**9), 10**9, 366, 3.5, "abc", float("nan"), [1], True])
def test_absurd_num_nights_is_quarantined(raw_payload, nights):
    page = first_result(raw_payload, lambda c: c["bookingDetails"].__setitem__("numNights", nights))

    assert len(page.rejected) == 1 and len(page.reviews) == 4


@pytest.mark.parametrize("field,value", [
    ("checkinDate", "1900-01-01"), ("checkinDate", "9999-12-31"), ("checkoutDate", "9999-12-31"),
    ("checkinDate", "not-a-date"), ("checkoutDate", "1900-01-01"),
])
def test_absurd_stay_dates_are_quarantined(raw_payload, field, value):
    page = first_result(raw_payload, lambda c: c["bookingDetails"].__setitem__(field, value))

    assert len(page.rejected) == 1


def test_checkout_before_checkin_is_quarantined(raw_payload):
    def swap(c):
        c["bookingDetails"]["checkinDate"], c["bookingDetails"]["checkoutDate"] = "2026-09-18", "2026-09-10"
    assert len(first_result(raw_payload, swap).rejected) == 1


@pytest.mark.parametrize("votes", [-1, 10**12, "many", 1.5, [1], True, float("inf")])
def test_absurd_helpful_votes_is_quarantined(raw_payload, votes):
    page = first_result(raw_payload, lambda c: c.__setitem__("helpfulVotesCount", votes))

    assert len(page.rejected) == 1 and len(page.reviews) == 4


def test_rating_nan_never_reaches_the_database():
    with pytest.raises(Exception):
        Review(review_key="k1", property=SLUG, rating=float("nan"), review_date="2026-09-01")


# =====================================================================================
# S03  Poisoned text: giant strings, control chars, bidi / zero-width, absurd metadata
# =====================================================================================
@pytest.mark.parametrize("name", ["title", "liked", "disliked", "reply"])
def test_multi_megabyte_text_is_truncated_to_the_documented_limit(raw_payload, name):
    huge = "A" * (5 * 1024 * 1024)
    def poison(c):
        if name == "reply":
            c["partnerReply"]["reply"] = huge
        else:
            c["textDetails"][{"title": "title", "liked": "positiveText", "disliked": "negativeText"}[name]] = huge
    page = first_result(raw_payload, poison)

    r = page.reviews[0]
    value = {"title": r.title, "liked": r.liked, "disliked": r.disliked, "reply": r.host_reply}[name]
    assert len(value) <= 5000
    assert value.endswith("…")                  # truncation is visible, not silent


@pytest.mark.parametrize("field", ["countryName", "guestTypeTranslation"])
def test_huge_short_metadata_is_bounded(raw_payload, field):
    page = first_result(raw_payload, lambda c: c["guestDetails"].__setitem__(field, "x" * 100_000))

    r = page.reviews[0]
    assert len(r.reviewer_country or "") <= 200 and len(r.traveller_type or "") <= 200


def test_huge_room_name_is_bounded(raw_payload):
    page = first_result(raw_payload, lambda c: c["bookingDetails"]["roomType"].__setitem__("name", "r" * 100_000))
    assert len(page.reviews[0].room_type) <= 200


@pytest.mark.parametrize("nasty", [
    "a\x00b", "a\x07b", "a\x1b[31mRED\x1b[0mb", "a\x7fb", "a\x85b", "a\u009bb",
    "a‮b", "a‪b", "a⁦b", "a⁩b", "a​b", "a‌b", "a﻿b", "a⁠b", "a‎b",
    "a\ud800b", "a\udfffb", "a￾b",
])
def test_control_bidi_zero_width_and_surrogates_are_stripped_from_every_text_field(raw_payload, nasty):
    def poison(c):
        c["textDetails"]["title"] = nasty
        c["textDetails"]["positiveText"] = nasty
        c["textDetails"]["negativeText"] = nasty
        c["partnerReply"]["reply"] = nasty
        c["guestDetails"]["countryName"] = nasty
        c["bookingDetails"]["roomType"]["name"] = nasty
    r = first_result(raw_payload, poison).reviews[0]

    for value in (r.title, r.liked, r.disliked, r.host_reply, r.reviewer_country, r.room_type):
        assert value is not None
        assert value.startswith("a") and value.endswith("b")
        for ch in value:
            assert ch.isprintable() or ch in "\n\t", repr(ch)
        value.encode("utf-8")                    # lone surrogates would blow up the SQLite binding


def test_html_entities_in_host_reply_cannot_smuggle_control_chars_past_the_filter(raw_payload):
    # reply text is html.unescape()d, so the filter must run AFTER unescaping.
    r = first_result(raw_payload, lambda c: c["partnerReply"].__setitem__("reply", "x&#27;[31m&#0;&#x202E;y&#8203;z")).reviews[0]

    assert "\x1b" not in r.host_reply and "\x00" not in r.host_reply
    assert "‮" not in r.host_reply and "​" not in r.host_reply


def test_newlines_and_tabs_survive_in_long_text_but_not_in_single_line_fields(raw_payload):
    def poison(c):
        c["textDetails"]["negativeText"] = "line one\nline two\r\n\ttabbed"
        c["textDetails"]["title"] = "one\ntwo\r\nthree"
        c["guestDetails"]["countryName"] = "Aus\ntralia"
    r = first_result(raw_payload, poison).reviews[0]

    assert r.disliked == "line one\nline two\n\ttabbed"
    assert "\n" not in r.title and "\r" not in r.title
    assert "\n" not in r.reviewer_country


@pytest.mark.parametrize("lang", ["en" * 500, "../../etc", "en'; DROP TABLE reviews;--", "\x1b[31m", "<script>", "e", "", "😀😀", "en-GB-x-very-long-subtag-chain"])
def test_absurd_language_code_is_dropped_not_stored(raw_payload, lang):
    r = first_result(raw_payload, lambda c: c["textDetails"].__setitem__("lang", lang)).reviews[0]

    assert r.language is None


@pytest.mark.parametrize("lang", ["en", "fr", "pt-br", "zh-CN", "zh_TW", "ZH"])
def test_normal_language_codes_still_pass(raw_payload, lang):
    r = first_result(raw_payload, lambda c: c["textDetails"].__setitem__("lang", lang)).reviews[0]

    assert r.language == lang


@pytest.mark.parametrize("key", [
    "", " ", "a b", "../../etc/passwd", "k\n", "k\x00", "k;DROP", "k'--", 'k"', "ключ", "k" * 129, "k" * 100_000,
    "-leading-dash", ".hidden", "a/b", "a\\b", "<b>x</b>", "k‮", "%00", "a?b=c", "k\x1b[31m",
])
def test_review_key_with_odd_characters_or_length_is_rejected(raw_payload, key):
    page = first_result(raw_payload, lambda c: c.__setitem__("reviewUrl", key))

    assert len(page.rejected) == 1 and len(page.reviews) == 4
    rk = page.rejected[0].review_key
    assert rk is None or (len(rk) <= 128 and all(ch.isprintable() for ch in rk))


@pytest.mark.parametrize("key", ["b5dd03c083f5278b", "p0-r0", "olympic-paddington-0-1", "A1", "a.b_c-d", "x" * 128])
def test_ordinary_review_keys_are_accepted(raw_payload, key):
    page = first_result(raw_payload, lambda c: c.__setitem__("reviewUrl", key))

    assert page.reviews[0].review_key == key


@pytest.mark.parametrize("slug", ["", "A", "a b", "a'; DROP TABLE reviews;--", "../x", "x" * 65, "-a", "a\n"])
def test_review_property_slug_is_constrained(slug):
    with pytest.raises(Exception):
        Review(review_key="k", property=slug, rating=5, review_date="2026-09-01")


def test_one_million_cards_on_one_page_is_refused_cheaply(raw_payload):
    p = copy.deepcopy(raw_payload)
    p["data"]["reviewListFrontend"]["reviewCard"] = [None] * 1_000_000

    with pytest.raises(ParseError, match="cards"):
        parse_page(p, SLUG)


def test_duplicate_keys_inside_one_page_are_quarantined_not_applied_twice(raw_payload):
    p = copy.deepcopy(raw_payload)
    cards = p["data"]["reviewListFrontend"]["reviewCard"]
    evil = copy.deepcopy(cards[0])
    evil["reviewScore"] = 1.0
    evil["textDetails"]["negativeText"] = "second copy tries to overwrite the first"
    cards.append(evil)

    page = parse_page(p, SLUG)

    assert [r.review_key for r in page.reviews].count(cards[0]["reviewUrl"]) == 1
    assert page.reviews[0].rating == 5.0                 # first one wins
    assert len(page.rejected) == 1 and "duplicate" in page.rejected[0].reason


def test_quarantine_reason_and_key_are_bounded_and_clean(raw_payload):
    page = first_result(raw_payload, lambda c: c.__setitem__("reviewUrl", "\x1b[31m" + "k" * 10_000))

    rej = page.rejected[0]
    assert len(rej.reason) <= 300
    assert "\x1b" not in rej.reason and (rej.review_key is None or "\x1b" not in rej.review_key)


def test_reason_does_not_echo_attacker_text_unbounded(raw_payload):
    page = first_result(raw_payload, lambda c: c.__setitem__("reviewScore", "Z" * 100_000))

    assert len(page.rejected[0].reason) <= 300


def test_deeply_nested_json_inside_a_text_field_is_quarantined_not_a_recursion_crash(raw_payload):
    deep = cur = {}
    for _ in range(50_000):
        cur["a"] = {}
        cur = cur["a"]
    page = first_result(raw_payload, lambda c: c["textDetails"].__setitem__("positiveText", deep))

    assert len(page.rejected) == 1


# =====================================================================================
# S04  Key collision across properties: B must never move or overwrite A's review
# =====================================================================================
OTHER = "venus-surry-hills"


@pytest.fixture
def store():
    s = ReviewStore(":memory:")
    yield s
    s.close()


def test_property_b_cannot_overwrite_or_steal_property_a_review_with_a_reused_key(store, sample_page):
    victim = sample_page.reviews[0]
    store.upsert_reviews([victim])
    before = dict(store.get(victim.review_key))

    hostile = victim.model_copy(update={"property": OTHER, "rating": 1.0, "liked": "pwned", "disliked": "pwned",
                                         "host_reply": "pwned"})
    result = store.upsert_reviews([hostile])

    after = dict(store.get(victim.review_key))
    assert after == before                        # nothing about A's row moved, not even last_seen
    assert store.count(SLUG) == 1 and store.count(OTHER) == 0
    assert (result.new, result.updated) == (0, 0)
    assert result.conflicts == 1


def test_key_collision_is_recorded_in_quarantine_under_the_hostile_property(store, sample_page):
    victim = sample_page.reviews[0]
    store.upsert_reviews([victim])

    store.upsert_reviews([victim.model_copy(update={"property": OTHER})])

    rows = store.quarantined(OTHER)
    assert len(rows) == 1
    assert rows[0]["review_key"] == victim.review_key
    assert "another property" in rows[0]["reason"]


def test_collision_does_not_resurrect_a_missing_flag_on_the_victim(store, sample_page):
    victim = sample_page.reviews[0]
    store.upsert_reviews([victim])
    store.mark_missing(SLUG, set())                       # A's review is now flagged missing
    assert store.get(victim.review_key)["missing_since"] is not None

    store.upsert_reviews([victim.model_copy(update={"property": OTHER})])

    assert store.get(victim.review_key)["missing_since"] is not None


def test_collector_counts_a_cross_property_collision_as_rejected(store, sample_page):
    from scraper.collector import collect_property
    victim = sample_page.reviews[0]
    store.upsert_reviews([victim])
    hostile_page = ParsedPage(reviews=[victim.model_copy(update={"property": OTHER})], rejected=[], reported_total=None)

    s = collect_property(OTHER, [hostile_page], store, mode="full")

    assert s.new == 0 and s.rejected == 1
    assert store.get(victim.review_key)["property"] == SLUG


def test_same_key_reupsert_for_the_same_property_still_updates_normally(store, sample_page):
    r = sample_page.reviews[0]
    store.upsert_reviews([r])

    result = store.upsert_reviews([r.model_copy(update={"host_reply": "legit later reply"})])

    assert (result.updated, result.conflicts) == (1, 0)


# =====================================================================================
# S05  SQL injection: everything is parameterised
# =====================================================================================
SQLI = ["'; DROP TABLE reviews;--", "\" OR 1=1 --", "x'); DELETE FROM reviews; --", "1; ATTACH DATABASE '/tmp/x' AS y;--",
        "Robert'); DROP TABLE quarantine;--", "%' OR '1'='1", "\\'; --"]


def tables(db):
    return {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


@pytest.mark.parametrize("payload", SQLI)
def test_sql_payload_in_every_text_field_is_stored_as_inert_text(raw_payload, payload, store):
    def poison(c):
        c["textDetails"].update(title=payload, positiveText=payload, negativeText=payload)
        c["partnerReply"]["reply"] = payload
        c["guestDetails"]["countryName"] = payload
        c["guestDetails"]["guestTypeTranslation"] = payload
        c["bookingDetails"]["roomType"]["name"] = payload
    page = first_result(raw_payload, poison)

    store.upsert_reviews(page.reviews)

    assert {"reviews", "quarantine", "scrape_runs"} <= tables(store._db)
    assert store.count(SLUG) == 5
    row = store.get(page.reviews[0].review_key)
    assert row["liked"] == payload and row["title"] == payload


@pytest.mark.parametrize("payload", SQLI)
def test_sql_payload_as_review_key_and_property_bypassing_the_model_is_still_inert(payload, store):
    # model_construct skips validation: proves the STORE is parameterised, not merely that the model filters.
    r = Review.model_construct(review_key=payload, property=payload, rating=5.0, review_date="2026-09-01", title=payload,
                               liked=payload, disliked=payload, language=payload, reviewer_country=payload,
                               traveller_type=payload, room_type=payload, nights=1, checkin_date=None,
                               checkout_date=None, host_reply=payload, helpful_votes=0)
    from datetime import date
    r.review_date = date(2026, 9, 1)

    store.upsert_reviews([r])
    store.upsert_reviews([r])

    assert store.count(payload) == 1
    assert store.get(payload)["property"] == payload
    assert store.known_keys(payload) == {payload}
    store.mark_missing(payload, set())
    store.quarantine(payload, [RejectedReview(review_key=payload, reason=payload)])
    assert store.quarantined(payload)[0]["reason"] == payload
    run = store.start_run(payload, payload)
    store.finish_run(run, "failed", 0, 0, 0, 0, payload)
    assert store.latest_run(payload)["error"] == payload
    assert store.last_successful_run(payload) is None
    assert store.close_stale_runs(payload) == 0
    assert {"reviews", "quarantine", "scrape_runs"} <= tables(store._db)


def test_sql_built_with_f_strings_only_interpolates_static_identifiers():
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).parent.parent / "scraper" / "store.py").read_text())
    interpolated = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") in {"execute", "executemany", "executescript"}:
            for arg in node.args[:1]:
                for sub in ast.walk(arg):
                    if isinstance(sub, ast.FormattedValue):
                        interpolated.add(ast.unparse(sub.value))
    # cols come from Review.model_dump() keys (a fixed schema), the rest are '?' markers or fixed column names.
    assert interpolated <= {"','.join(cols)", "','.join('?' * len(cols))", "sets", "column", "ddl", "c"} , interpolated


# =====================================================================================
# S06  Storage exhaustion: quarantine growth, oversized error strings
# =====================================================================================
def test_hostile_page_cannot_flood_the_quarantine_table(store):
    from scraper import store as store_module
    flood = [RejectedReview(review_key=f"k{i}", reason="bad") for i in range(100_000)]

    store.quarantine(SLUG, flood)

    assert len(store.quarantined(SLUG)) <= store_module.MAX_QUARANTINE_PER_CALL


def test_quarantine_table_has_a_rolling_ceiling_across_many_pages(store, monkeypatch):
    from scraper import store as store_module
    monkeypatch.setattr(store_module, "MAX_QUARANTINE_ROWS", 120)
    for page in range(50):
        store.quarantine(SLUG, [RejectedReview(review_key=f"p{page}-{i}", reason="bad") for i in range(40)])

    rows = store.quarantined(SLUG)
    assert len(rows) <= 120
    assert any(r["review_key"] == "p49-0" for r in rows)       # newest evidence is kept, oldest is dropped
    assert not any(r["review_key"] == "p0-0" for r in rows)


def test_quarantine_does_not_prune_other_properties(store, monkeypatch):
    from scraper import store as store_module
    monkeypatch.setattr(store_module, "MAX_QUARANTINE_ROWS", 10)
    store.quarantine(OTHER, [RejectedReview(review_key="keepme", reason="x")])
    for i in range(30):
        store.quarantine(SLUG, [RejectedReview(review_key=f"k{i}", reason="bad")])

    assert len(store.quarantined(OTHER)) == 1


def test_quarantine_reason_and_key_are_clamped_by_the_store_itself(store):
    store.quarantine(SLUG, [RejectedReview(review_key="K" * 10_000, reason="\x1b[31m" + "R" * 1_000_000 + "\n\x00")])

    row = store.quarantined(SLUG)[0]
    assert len(row["reason"]) <= 300 and len(row["review_key"]) <= 128
    assert "\x1b" not in row["reason"] and "\n" not in row["reason"] and "\x00" not in row["reason"]


def test_oversized_error_text_is_capped_and_cleaned_in_the_run_ledger(store):
    run = store.start_run(SLUG, "full")

    store.finish_run(run, "failed", 0, 0, 0, 0, "\x1b[2J\x1b[31m" + "E" * 5_000_000 + "\nfake log line\r\n\x00")

    err = store.latest_run(SLUG)["error"]
    assert len(err) <= 500
    assert "\x1b" not in err and "\n" not in err and "\r" not in err and "\x00" not in err


def test_ledger_status_is_restricted_to_the_known_values(store):
    run = store.start_run(SLUG, "full")

    with pytest.raises(ValueError):
        store.finish_run(run, "ok'; DROP TABLE reviews;--", 0, 0, 0, 0, None)

    assert "reviews" in tables(store._db)
    assert store.latest_run(SLUG)["status"] == "running"


# =====================================================================================
# S07  Infinite / stuck pagination
# =====================================================================================
class Endless:
    """A hostile server: yields pages forever. Counts how many the collector pulled."""

    def __init__(self, make_page):
        self.make_page, self.pulled = make_page, 0

    def __iter__(self):
        n = 0
        while True:
            self.pulled += 1
            yield self.make_page(n)
            n += 1


def unique_page(sample_page, n, size=10, total=None):
    base = sample_page.reviews[0]
    return ParsedPage(reviews=[base.model_copy(update={"review_key": f"e{n}-{i}"}) for i in range(size)],
                      rejected=[], reported_total=total)


def test_endless_server_with_no_max_pages_is_stopped_by_the_hard_ceiling(sample_page, store, monkeypatch):
    from scraper import collector
    monkeypatch.setattr(collector, "HARD_MAX_PAGES", 25)
    pages = Endless(lambda n: unique_page(sample_page, n))

    s = collector.collect_property(SLUG, pages, store, mode="full", max_pages=None)

    assert s.status == "failed"
    assert "ceiling" in s.error and "25" in s.error
    assert pages.pulled <= 26                  # never drained: at most one page past the ceiling is requested
    assert store.latest_run(SLUG)["status"] == "failed"
    assert store.count(SLUG) == 250            # what was already saved is kept


def test_default_hard_ceiling_exists_and_is_sane():
    from scraper import collector, config
    assert collector.HARD_MAX_PAGES == config.HARD_MAX_PAGES
    assert 200 <= config.HARD_MAX_PAGES <= 2000


def test_max_pages_larger_than_the_ceiling_cannot_defeat_it(sample_page, store, monkeypatch):
    from scraper import collector
    monkeypatch.setattr(collector, "HARD_MAX_PAGES", 10)
    pages = Endless(lambda n: unique_page(sample_page, n))

    s = collector.collect_property(SLUG, pages, store, mode="full", max_pages=10**9)

    assert s.status == "failed" and pages.pulled <= 11


def test_server_repeating_the_same_page_forever_fails_the_run_with_a_clear_message(sample_page, store):
    from scraper.collector import collect_property
    same = unique_page(sample_page, 0)
    pages = Endless(lambda n: same)

    s = collect_property(SLUG, pages, store, mode="full", max_pages=200)

    assert s.status == "failed"
    assert "repeat" in s.error.lower()
    assert pages.pulled <= 3
    assert s.pages <= 2


def test_repeated_page_also_fails_incremental_runs(sample_page, store):
    from scraper.collector import collect_property
    same = unique_page(sample_page, 0)

    s = collect_property(SLUG, Endless(lambda n: same), store, mode="incremental")

    assert s.status == "failed" and "repeat" in s.error.lower()


def test_a_page_that_comes_back_later_is_also_caught(sample_page, store):
    from scraper.collector import collect_property
    a, b = unique_page(sample_page, 0), unique_page(sample_page, 1)
    pages = [a, b, a, b, a]

    s = collect_property(SLUG, pages, store, mode="full")

    assert s.status == "failed" and "repeat" in s.error.lower()


def test_pages_that_merely_overlap_a_little_are_fine(sample_page, store):
    """A new review posted mid-run shifts everything by one; that must not look like a loop."""
    from scraper.collector import collect_property
    base = sample_page.reviews[0]
    mk = lambda ks: ParsedPage(reviews=[base.model_copy(update={"review_key": k}) for k in ks], rejected=[], reported_total=None)
    pages = [mk(["a1", "a2", "a3"]), mk(["a3", "b1", "b2"]), mk(["b2", "c1", "c2"])]

    s = collect_property(SLUG, pages, store, mode="full")

    assert s.status == "ok" and s.pages == 3 and store.count(SLUG) == 7


def test_endless_stream_of_all_rejected_pages_is_stopped_too(sample_page, store, monkeypatch):
    from scraper import collector
    monkeypatch.setattr(collector, "HARD_MAX_PAGES", 12)
    junk = ParsedPage(reviews=[], rejected=[RejectedReview(review_key=None, reason="bad")] * 5, reported_total=None)
    pages = Endless(lambda n: junk)

    s = collector.collect_property(SLUG, pages, store, mode="full")

    assert s.status == "failed" and pages.pulled <= 13
    assert len(store.quarantined(SLUG)) <= 12 * 5


def test_unexpected_exception_from_the_fetcher_closes_the_ledger_instead_of_crashing(store):
    from scraper.collector import collect_property

    def boom():
        raise OverflowError("\x1b[31mhostile \n" + "x" * 10_000)
        yield  # pragma: no cover

    s = collect_property(SLUG, boom(), store, mode="full")

    assert s.status == "failed"
    assert "OverflowError" in s.error and "\x1b" not in s.error and len(s.error) <= 500
    assert store.latest_run(SLUG)["status"] == "failed"


# =====================================================================================
# S08  SQLite robustness: locked database, non-SQLite file, atomic batches
# =====================================================================================
def make_db(tmp_path, name="t.db"):
    path = tmp_path / name
    s = ReviewStore(str(path))
    return s, path


def test_locked_database_fails_with_a_clear_store_error_not_a_raw_sqlite_traceback(tmp_path, sample_page):
    from scraper.errors import StoreError
    s, path = make_db(tmp_path)
    s.upsert_reviews(sample_page.reviews)
    other = sqlite3.connect(str(path), isolation_level=None)
    other.execute("BEGIN EXCLUSIVE")
    try:
        with pytest.raises(StoreError, match="locked"):
            ReviewStore(str(path), busy_timeout_s=0.2)
        with pytest.raises(StoreError, match="locked"):
            s._db.execute("PRAGMA busy_timeout=200")   # a store opened earlier, then another process grabs the file
            s.upsert_reviews([sample_page.reviews[0].model_copy(update={"review_key": "newkey1"})])
    finally:
        other.execute("ROLLBACK")
        other.close()
    assert s.count(SLUG) == 5                         # nothing was corrupted or half written


def test_store_waits_for_a_busy_database_instead_of_failing_instantly(tmp_path):
    from scraper import store as store_module
    s, path = make_db(tmp_path)
    assert store_module.BUSY_TIMEOUT_S >= 10
    assert s._db.execute("PRAGMA busy_timeout").fetchone()[0] == int(store_module.BUSY_TIMEOUT_S * 1000)


def test_a_file_that_is_not_sqlite_is_refused_untouched(tmp_path):
    from scraper.errors import StoreError
    path = tmp_path / "notes.db"
    path.write_bytes(b"this is my diary, not a database\n" * 100)
    before = path.read_bytes()

    with pytest.raises(StoreError, match="not a SQLite database"):
        ReviewStore(str(path))

    assert path.read_bytes() == before


def test_a_malformed_sqlite_file_is_refused_with_a_clear_error(tmp_path):
    from scraper.errors import StoreError
    s, path = make_db(tmp_path)
    s.close()
    data = bytearray(path.read_bytes())
    data[100:200] = b"\xff" * 100                    # keep the header, wreck the b-tree
    path.write_bytes(bytes(data))

    with pytest.raises(StoreError):
        ReviewStore(str(path)).count(SLUG)


def test_opening_a_directory_gives_a_clear_error(tmp_path):
    from scraper.errors import StoreError
    with pytest.raises(StoreError):
        ReviewStore(str(tmp_path))


def test_a_failing_batch_is_rolled_back_whole_not_half_committed(store, sample_page):
    good = sample_page.reviews[:2]
    poison = Review.model_construct(**{**good[0].model_dump(), "review_key": "poison", "liked": "bad \ud800 surrogate"})

    with pytest.raises(Exception):
        store.upsert_reviews([good[0], poison, good[1]])
    store.start_run(SLUG, "full")                      # any later commit must not sneak the partial batch in

    assert store.count(SLUG) == 0


# =====================================================================================
# S09  CLI: --db, --property, --max-pages
# =====================================================================================
from scraper import run as run_module  # noqa: E402
from scraper.collector import CollectionSummary  # noqa: E402


def no_browser(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the browser must not be reached")
    monkeypatch.setattr(run_module, "fetch_pages", boom)


@pytest.mark.parametrize("huge", ["1000000000", "1001", str(10**30), "9" * 5000])
def test_cli_bounds_a_huge_max_pages(huge, tmp_path, capsys, monkeypatch):
    no_browser(monkeypatch)
    with pytest.raises(SystemExit):
        run_module.main(["--max-pages", huge, "--db", str(tmp_path / "t.db")])

    err = capsys.readouterr().err
    assert "at most" in err or "positive whole number" in err      # 5000 digits overflow int(): still a clean refusal
    assert len(err) < 1500
    assert not (tmp_path / "t.db").exists()


def test_cli_accepts_the_documented_larger_cap(tmp_path, monkeypatch):
    seen = {}
    monkeypatch.setattr(run_module, "fetch_pages", lambda *a, **k: iter(()))
    monkeypatch.setattr(run_module, "collect_property", lambda *a, **k: seen.update(k) or CollectionSummary(status="ok"))

    run_module.main(["--property", "chateau-de-venus", "--max-pages", "400", "--db", str(tmp_path / "t.db")])

    assert seen["max_pages"] == 400


@pytest.mark.parametrize("bad", ["", ":memory:", "file:x.db?mode=memory&cache=shared", "file::memory:", "a\x00b.db", " "])
def test_cli_refuses_db_paths_that_would_silently_lose_or_misplace_data(bad, tmp_path, capsys, monkeypatch):
    no_browser(monkeypatch)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        run_module.main(["--property", "chateau-de-venus", "--db", bad])

    assert list(tmp_path.iterdir()) == []              # nothing created next to us


def test_cli_refuses_a_directory_and_a_missing_parent_directory(tmp_path, capsys, monkeypatch):
    no_browser(monkeypatch)
    for bad in (str(tmp_path), str(tmp_path / "no" / "such" / "dir" / "x.db")):
        with pytest.raises(SystemExit):
            run_module.main(["--db", bad])
    assert not (tmp_path / "no").exists()              # we do not mkdir -p arbitrary paths either


@pytest.mark.parametrize("argv", [["--property", "--db", "x.db"], ["--db", "--property"], ["--property"], ["--max-pages"]])
def test_cli_option_injection_through_missing_values_is_an_argparse_error(argv, tmp_path, monkeypatch):
    no_browser(monkeypatch)
    monkeypatch.chdir(tmp_path)
    with pytest.raises(SystemExit):
        run_module.main(argv)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("evil", ["\x1b[2J\x1b[31mpwned", "all; rm -rf /", "../../etc/passwd", "olympic-paddington\nforged: ok",
                                  "x" * 100_000, "--db=/tmp/evil.db", "ALL"])
def test_cli_unknown_property_is_rejected_with_a_clean_bounded_message(evil, tmp_path, capsys, monkeypatch):
    no_browser(monkeypatch)
    with pytest.raises(SystemExit):
        run_module.main(["--property", evil, "--db", str(tmp_path / "t.db")])

    err = capsys.readouterr().err
    assert "\x1b" not in err and "forged: ok\n" not in err
    assert len(err) < 2000
    assert not (tmp_path / "t.db").exists()


def test_cli_property_all_is_the_only_wildcard(tmp_path, monkeypatch):
    monkeypatch.setattr(run_module, "fetch_pages", lambda *a, **k: iter(()))
    for odd in ("*", "%", "olympic%", ".*"):
        with pytest.raises(SystemExit):
            run_module.main(["--property", odd, "--db", str(tmp_path / "t.db")])


# =====================================================================================
# S10  Terminal and log injection through remote-controlled error text
# =====================================================================================
def test_cli_never_prints_escape_sequences_or_forged_lines_from_a_remote_error(tmp_path, capsys, monkeypatch):
    nasty = "\x1b[2J\x1b[1;31mFAKE\x1b[0m\nthe-hotel: ok pages=999 new=999\r\x07" + "A" * 50_000
    monkeypatch.setattr(run_module, "collect_property",
                        lambda *a, **k: CollectionSummary(status="failed", error=nasty))
    monkeypatch.setattr(run_module, "fetch_pages", lambda *a, **k: iter(()))

    run_module.main(["--property", "chateau-de-venus", "--db", str(tmp_path / "t.db")])

    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out and "\r" not in out
    assert not any(line.startswith("the-hotel") for line in out.splitlines())
    assert len(out) < 2000


def test_a_failing_fetch_with_hostile_text_ends_up_clean_in_stdout_and_in_the_ledger(tmp_path, capsys, monkeypatch):
    from scraper.errors import FetchError

    def hostile(url, slug, **kw):
        raise FetchError("\x1b]0;owned\x07 \x1b[31m\nforged line\n")
        yield  # pragma: no cover
    monkeypatch.setattr(run_module, "fetch_pages", hostile)

    code = run_module.main(["--property", "chateau-de-venus", "--db", str(tmp_path / "t.db")])

    out = capsys.readouterr().out
    assert code == 1 and "\x1b" not in out and "\x07" not in out
    err = sqlite3.connect(str(tmp_path / "t.db")).execute("select error from scrape_runs").fetchone()[0]
    assert "\x1b" not in err and "\n" not in err


def test_cli_reports_a_non_sqlite_db_as_a_clean_error_not_a_traceback(tmp_path, capsys, monkeypatch):
    no_browser(monkeypatch)
    bad = tmp_path / "diary.db"
    bad.write_text("dear diary")

    code = run_module.main(["--property", "chateau-de-venus", "--db", str(bad)])

    captured = capsys.readouterr()
    assert code == 2
    assert "not a SQLite database" in captured.err
    assert bad.read_text() == "dear diary"


def test_cli_reports_a_locked_db_as_a_clean_error(tmp_path, capsys, monkeypatch):
    from scraper import store as store_module
    no_browser(monkeypatch)
    path = tmp_path / "t.db"
    ReviewStore(str(path)).close()
    monkeypatch.setattr(store_module, "BUSY_TIMEOUT_S", 0.2)
    other = sqlite3.connect(str(path), isolation_level=None)
    other.execute("BEGIN EXCLUSIVE")
    try:
        code = run_module.main(["--property", "chateau-de-venus", "--db", str(path)])
    finally:
        other.execute("ROLLBACK")
        other.close()

    assert code == 2
    assert "locked" in capsys.readouterr().err


# =====================================================================================
# S11  Browser layer: URL allow-list, response origin, context hardening (pure helpers + fakes, no real browser)
# =====================================================================================
from scraper import browser  # noqa: E402
from scraper.errors import BlockedError, FetchError  # noqa: E402

GOOD_URLS = [
    "https://www.booking.com/hotel/au/olympic-paddington.html",
    "https://www.booking.com/hotel/au/chateau-de-venus.html",
    "https://www.booking.com/hotel/nz/some-place-2.html",
]
EVIL_URLS = [
    "http://www.booking.com/hotel/au/olympic-paddington.html",                       # no TLS
    "https://booking.com/hotel/au/olympic-paddington.html",                          # other host (apex)
    "https://www.booking.com.evil.example/hotel/au/x.html",                          # suffix trick
    "https://evil.example/www.booking.com/hotel/au/x.html",
    "https://www.booking.com@evil.example/hotel/au/x.html",                          # userinfo trick
    "https://evil.example@www.booking.com/hotel/au/x.html",
    "https://www.booking.com:8443/hotel/au/x.html",                                  # odd port
    "https://www.booking.com/hotel/au/x.html?redirect=https://evil.example",         # query on the strict form
    "https://www.booking.com/hotel/au/x.html#frag",
    "https://www.booking.com/hotel/au/../../evil.html",
    "https://www.booking.com/hotel/au/x/../y.html",
    "https://www.booking.com/hotel/aus/x.html",
    "https://www.booking.com/hotel/au/x.html\n",
    "https://www.booking.com/hotel/au/x.html\r\nHost: evil.example",
    "https://www.booking.com/hotel/au/x y.html",
    "https://www.booking.com/hotel/au/.html",
    "https://www.booking.com/other/au/x.html",
    "https://www.booking.com//evil.example/hotel/au/x.html",
    "javascript:alert(1)", "file:///etc/passwd", "data:text/html,<script>1</script>", "ftp://www.booking.com/hotel/au/x.html",
    "https://WWW.BOOKING.COM.evil.example/hotel/au/x.html", "https://www.booking.com\\@evil.example/hotel/au/x.html",
    "https://127.0.0.1/hotel/au/x.html", "https://169.254.169.254/latest/meta-data/", "", " ", None, 5, "https://www.booking.com/hotel/au/" + "a" * 5000 + ".html",
]


@pytest.mark.parametrize("url", GOOD_URLS)
def test_allow_list_accepts_real_property_urls(url):
    assert browser.is_allowed_property_url(url)


@pytest.mark.parametrize("url", EVIL_URLS)
def test_allow_list_rejects_ssrf_and_open_redirect_urls(url):
    assert not browser.is_allowed_property_url(url)


def test_every_configured_property_url_and_slug_passes_the_allow_list():
    from scraper.config import PROPERTIES
    from scraper.models import SLUG_RE
    for p in PROPERTIES:
        assert browser.is_allowed_property_url(p.url), p.url
        assert SLUG_RE.fullmatch(p.slug), p.slug


@pytest.mark.parametrize("url", EVIL_URLS[:-5] + [""])
def test_fetch_pages_refuses_a_bad_url_before_any_browser_is_launched(url, monkeypatch):
    def launched(*a, **k):
        raise AssertionError("browser launched for a URL that is not on the allow-list")
    monkeypatch.setattr(browser, "sync_playwright", launched)

    with pytest.raises(FetchError, match="allow-list"):
        next(browser.fetch_pages(url, SLUG))


@pytest.mark.parametrize("url,ok", [
    ("https://www.booking.com/hotel/au/olympic-paddington.html", True),
    ("https://www.booking.com/hotel/au/olympic-paddington.en-gb.html?aid=1&label=x#reviews", True),   # Booking adds params
    ("https://www.booking.com/hotel/au/olympic-paddington.html?sid=abc", True),
    ("https://evil.example/hotel/au/olympic-paddington.html", False),
    ("https://www.booking.com.evil.example/hotel/au/olympic-paddington.html", False),
    ("https://www.booking.com@evil.example/hotel/au/x.html", False),
    ("https://www.booking.com/account/signin.html", False),            # redirected to a login page
    ("https://www.booking.com/hotel/au/x.html@evil.example", False),
    ("http://www.booking.com/hotel/au/x.html", False),
    ("about:blank", False), ("chrome-error://chromewebdata/", False), ("", False), (None, False),
])
def test_final_url_after_navigation_must_still_be_on_the_allow_list(url, ok):
    assert browser.is_allowed_final_url(url) is ok


class FakeLocator:
    def count(self):
        return 1

    def is_disabled(self):
        return True

    @property
    def first(self):
        return self


class FakePage:
    def __init__(self, lands_on):
        self.lands_on, self.url, self.goto_calls = lands_on, "about:blank", []

    def goto(self, url, **kw):
        self.goto_calls.append(url)
        self.url = self.lands_on

    def locator(self, sel):
        return FakeLocator()

    def wait_for_timeout(self, ms):
        pass


class FakePlaywright:
    """Records what the browser layer asked Playwright to do."""

    def __init__(self, lands_on):
        self.page = FakePage(lands_on)
        self.launch_kwargs = self.context_kwargs = None
        self.closed = False
        self.persistent_used = False
        outer = self

        class Ctx:
            def new_page(self_inner):
                return outer.page

        class Browser:
            def new_context(self_inner, **kw):
                outer.context_kwargs = kw
                return Ctx()

            def close(self_inner):
                outer.closed = True

        class Chromium:
            def launch(self_inner, **kw):
                outer.launch_kwargs = kw
                return Browser()

            def launch_persistent_context(self_inner, *a, **kw):
                outer.persistent_used = True
                raise AssertionError("persistent profile would leave cookies and tokens on disk")

        self.chromium = Chromium()

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_open_redirect_after_navigation_is_caught_and_the_browser_is_closed(monkeypatch):
    fake = FakePlaywright(lands_on="https://evil.example/phish")
    monkeypatch.setattr(browser, "sync_playwright", fake)

    with pytest.raises(BlockedError, match="redirect"):
        next(browser.fetch_pages(GOOD_URLS[0], SLUG))

    assert fake.page.goto_calls == [GOOD_URLS[0]]
    assert fake.closed is True


def test_browser_context_is_fresh_in_memory_with_downloads_and_permissions_off(monkeypatch):
    fake = FakePlaywright(lands_on="https://evil.example/stop-here")
    monkeypatch.setattr(browser, "sync_playwright", fake)
    with pytest.raises(BlockedError):
        next(browser.fetch_pages(GOOD_URLS[0], SLUG))

    ctx = fake.context_kwargs
    assert ctx["accept_downloads"] is False
    assert ctx["permissions"] == []
    assert ctx["service_workers"] == "block"
    assert ctx["ignore_https_errors"] is False
    assert not any(k in ctx for k in ("storage_state", "user_data_dir", "record_video_dir", "record_har_path"))
    assert fake.persistent_used is False
    assert not any(k in fake.launch_kwargs for k in ("user_data_dir", "downloads_path"))
    assert "--no-sandbox" not in fake.launch_kwargs.get("args", [])
    assert "--disable-web-security" not in fake.launch_kwargs.get("args", [])


def test_browser_source_never_uses_a_persistent_profile_or_stored_state():
    import inspect
    src = inspect.getsource(browser)
    for forbidden in ("launch_persistent_context", "user_data_dir", "storage_state", "add_cookies", "set_extra_http_headers",
                      "--no-sandbox", "--disable-web-security", "ignore_https_errors=True"):
        assert forbidden not in src, forbidden


class FakeReq:
    def __init__(self, method="POST", post_data='{"operationName":"ReviewList"}'):
        self.method, self.post_data = method, post_data


class FakeResp:
    def __init__(self, url, body=b"{}", status=200, req=None):
        self.url, self._body, self.status, self.request = url, body, status, req or FakeReq()

    def body(self):
        return self._body

    def json(self):
        import json as _j
        return _j.loads(self._body)


@pytest.mark.parametrize("url,expected", [
    ("https://www.booking.com/dml/graphql?lang=en-gb", True),
    ("https://evil.example/graphql", False),                                        # third-party frame answering as 'graphql'
    ("https://www.booking.com.evil.example/graphql", False),
    ("https://evil.example/?x=https://www.booking.com/graphql", False),
    ("http://www.booking.com/dml/graphql", False),
    ("https://www.booking.com/no-api-here", False),
])
def test_only_booking_com_graphql_responses_are_trusted_as_review_data(url, expected):
    assert browser._is_review_list(FakeResp(url)) is expected


def test_review_list_filter_requires_post_and_the_operation_name():
    assert not browser._is_review_list(FakeResp("https://www.booking.com/dml/graphql", req=FakeReq(method="GET")))
    assert not browser._is_review_list(FakeResp("https://www.booking.com/dml/graphql", req=FakeReq(post_data="{}")))
    assert not browser._is_review_list(FakeResp("https://www.booking.com/dml/graphql", req=FakeReq(post_data=None)))


def test_response_body_over_the_size_limit_is_refused_before_parsing():
    resp = FakeResp("https://www.booking.com/dml/graphql", body=b"{" + b" " * (browser.MAX_RESPONSE_BYTES + 1) + b"}")

    with pytest.raises(FetchError, match="too large"):
        browser._read(resp, SLUG)


def test_deeply_nested_json_body_is_refused_as_not_json_not_a_recursion_crash():
    body = b"[" * 200_000 + b"]" * 200_000

    with pytest.raises(BlockedError):
        browser._read(FakeResp("https://www.booking.com/dml/graphql", body=body), SLUG)


@pytest.mark.parametrize("bad", [b'{"data": NaN}', b'{"data": Infinity}', b'{"data": -Infinity}'])
def test_nan_and_infinity_literals_in_the_json_body_are_refused(bad):
    with pytest.raises(BlockedError):
        browser._read(FakeResp("https://www.booking.com/dml/graphql", body=bad), SLUG)


@pytest.mark.parametrize("body", [b"[]", b'"x"', b"5", b"null", b'{"data": []}', b'{"data": {"reviewListFrontend": []}}'])
def test_json_of_the_wrong_shape_never_crashes_read(body):
    with pytest.raises((BlockedError, ParseError)):
        browser._read(FakeResp("https://www.booking.com/dml/graphql", body=body), SLUG)


def test_blocked_status_codes_inside_the_body_are_still_recognised():
    body = json.dumps({"data": {"reviewListFrontend": {"statusCode": 429, "message": "slow down"}}}).encode()

    with pytest.raises(BlockedError, match="429"):
        browser._read(FakeResp("https://www.booking.com/dml/graphql", body=body), SLUG)


def test_browser_page_ceiling_matches_the_collector_ceiling():
    from scraper.config import HARD_MAX_PAGES
    assert browser.MAX_PAGES == HARD_MAX_PAGES


# =====================================================================================
# S12  Privacy and secrets
# =====================================================================================
FORBIDDEN_COLUMN_WORDS = {"name", "username", "user", "avatar", "email", "phone", "photo", "picture", "image", "ip",
                          "address", "reviewer", "guest", "token", "cookie", "password", "session"}
ALLOWED_COLUMNS_WITH_FORBIDDEN_WORD = {"reviewer_country"}      # a country name only, reviewed and accepted (see docs)


def all_columns(db):
    out = {}
    for (table,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall():
        out[table] = [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
    return out


def test_no_table_has_a_column_that_could_hold_a_reviewer_name_avatar_or_contact_detail(store):
    for table, cols in all_columns(store._db).items():
        for col in cols:
            if col in ALLOWED_COLUMNS_WITH_FORBIDDEN_WORD:
                continue
            assert not (set(col.lower().split("_")) & FORBIDDEN_COLUMN_WORDS), f"{table}.{col}"


def test_review_model_has_no_field_for_personal_identifiers():
    for field in Review.model_fields:
        if field in ALLOWED_COLUMNS_WITH_FORBIDDEN_WORD:
            continue
        assert not (set(field.split("_")) & FORBIDDEN_COLUMN_WORDS), field


def test_parser_only_reads_an_explicit_allow_list_of_response_keys():
    import ast
    from pathlib import Path
    tree = ast.parse((Path(__file__).parent.parent / "scraper" / "parse.py").read_text())
    func = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_parse_card")
    keys = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant):
            keys.add(node.slice.value)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "get":
            keys.update(a.value for a in node.args[:1] if isinstance(a, ast.Constant))
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "_section":
            keys.update(a.value for a in node.args[1:2] if isinstance(a, ast.Constant))
    assert keys == {"reviewUrl", "reviewScore", "reviewedDate", "textDetails", "guestDetails", "bookingDetails", "roomType",
                    "partnerReply", "reply", "title", "positiveText", "negativeText", "lang", "countryName",
                    "guestTypeTranslation", "numNights", "checkinDate", "checkoutDate", "name", "helpfulVotesCount"}, keys


def test_reviewer_identity_fields_in_the_response_never_reach_the_database(raw_payload, store):
    secrets_ = ["TestGuestOne-USERNAME", "https://example.invalid/AVATAR-SECRET.png", "victim@example.invalid",
                "+61-400-000-000", "GUESTID-777", "Jane Q. Reviewer"]
    def poison(c):
        c["guestDetails"].update(username=secrets_[0], avatarUrl=secrets_[1], email=secrets_[2], phone=secrets_[3],
                                 userId=secrets_[4], fullName=secrets_[5])
        c["reviewer"] = {"name": secrets_[5], "email": secrets_[2]}
        c["bookingDetails"]["guestEmail"] = secrets_[2]
    page = first_result(raw_payload, poison)

    store.upsert_reviews(page.reviews)
    store.quarantine(SLUG, page.rejected)

    dump = json.dumps({t: [list(r) for r in store._db.execute(f"SELECT * FROM {t}")] for t in all_columns(store._db)}, default=str)
    for secret in secrets_:
        assert secret not in dump
    assert "avatar" not in dump.lower()


def _tracked_files(include_untracked=True):
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    try:
        out = subprocess.run(["git", "ls-files", "--cached"] + (["--others", "--exclude-standard"] if include_untracked else []), cwd=root,
                             capture_output=True, text=True, check=True, timeout=30).stdout.split("\n")
        files = [root / f for f in out if f]
    except Exception:
        files = [p for p in root.rglob("*") if p.is_file() and ".venv" not in p.parts and ".git" not in p.parts
                 and "__pycache__" not in p.parts]
    skip = {Path(__file__).resolve(), (root / "docs" / "security" / "scraper.md").resolve()}
    return [f for f in files if f.is_file() and f.resolve() not in skip]


SECRET_PATTERNS = {
    "aws access key": r"AKIA[0-9A-Z]{16}",
    "api key (sk-)": r"sk-[A-Za-z0-9_-]{20,}",
    "github token": r"gh[pousr]_[A-Za-z0-9]{20,}",
    "slack token": r"xox[abprs]-[A-Za-z0-9-]{10,}",
    "private key block": r"BEGIN [A-Z ]*PRIVATE KEY",
    "cookie header": r"(?i)\bcookie:\s*\S",
    "bearer token": r"(?i)\bbearer\s+[A-Za-z0-9._-]{20,}",
    "assigned secret": r"(?i)(api[_-]?key|secret|token|passw(or)?d|session[_-]?id)['\"]?\s*[:=]\s*['\"][A-Za-z0-9/+=_.-]{12,}['\"]",
    "mac home path": r"/Us" + r"ers/[A-Za-z0-9_.-]+/",
    "linux home path": r"/ho" + r"me/[a-z][a-z0-9_-]+/",
    "windows home path": r"(?i)[A-Z]:\\Us" + r"ers\\[A-Za-z0-9_. -]+\\",
}


def test_no_secret_looking_strings_or_absolute_home_paths_in_tracked_files():
    import re
    hits = []
    for path in _tracked_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label, pattern in SECRET_PATTERNS.items():
            m = re.search(pattern, text)
            if m:
                hits.append(f"{path.name}: {label}")
    assert hits == []


def test_no_database_env_cookie_or_key_files_are_tracked():
    import re
    bad = [f.name for f in _tracked_files(include_untracked=False)
           if re.search(r"(\.db|\.sqlite3?|\.pem|\.key|\.p12)$|^\.env$|cookies.*\.json$|storage_state.*\.json$", f.name)]
    assert bad == []


@pytest.mark.xfail(reason="OPEN HAND-OFF: .gitignore (outside the scraper scope) does not ignore data/reviews.db, so "
                          "'git add .' would commit scraped reviews. Add 'data/*.db' to .gitignore and this passes.",
                   strict=False)
def test_the_live_database_path_is_git_ignored():
    import subprocess
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    res = subprocess.run(["git", "check-ignore", "-q", "data/reviews.db"], cwd=root)
    assert res.returncode == 0


# =====================================================================================
# S13  Integrity of derived signals: invisible text must not fake a host reply
# =====================================================================================
@pytest.mark.parametrize("blank", ["​", "​‌﻿", "\x00", "\x1b", "   ", "\n\n", "‮", "&#8203;", "&#0;&#27;"])
def test_blank_or_invisible_host_reply_does_not_count_as_a_reply(raw_payload, blank):
    r = first_result(raw_payload, lambda c: c["partnerReply"].__setitem__("reply", blank)).reviews[0]

    assert r.host_reply is None
    assert r.has_host_reply is False


# =====================================================================================
# S14  A hostile or broken response must not mass-flag stored reviews as "missing"
# =====================================================================================
def test_empty_first_page_in_a_full_run_does_not_flag_every_stored_review_missing(store, sample_page):
    from scraper.collector import collect_property
    store.upsert_reviews(sample_page.reviews)
    empty = ParsedPage(reviews=[], rejected=[], reported_total=None)

    s = collect_property(SLUG, [empty], store, mode="full")

    assert s.status == "failed" and "no reviews" in s.error.lower()
    assert all(store.get(r.review_key)["missing_since"] is None for r in sample_page.reviews)


def test_a_short_response_that_trips_the_drift_check_does_not_flag_reviews_missing(store, sample_page):
    from scraper.collector import collect_property
    store.upsert_reviews(sample_page.reviews)
    one = ParsedPage(reviews=sample_page.reviews[:1], rejected=[], reported_total=5)   # claims 5, delivers 1... of 5 stored
    pages = [one]

    s = collect_property(SLUG, pages, store, mode="full")

    assert s.drift is True
    assert all(store.get(r.review_key)["missing_since"] is None for r in sample_page.reviews)


def test_genuinely_empty_property_is_still_fine(store):
    from scraper.collector import collect_property

    s = collect_property(SLUG, [ParsedPage(reviews=[], rejected=[], reported_total=0)], store, mode="full")

    assert s.status == "ok"
