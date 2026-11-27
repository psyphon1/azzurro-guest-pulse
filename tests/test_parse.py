import json
from pathlib import Path

import pytest

from scraper.parse import parse_reviews

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def payload():
    return json.loads((FIXTURES / "olympic_reviewlist_page1.json").read_text())


def test_parses_every_review_card(payload):
    reviews = parse_reviews(payload, property_slug="olympic-paddington")

    assert len(reviews) == 5
    assert reviews[0].review_key == "b5dd03c083f5278b"
    assert reviews[0].rating == 5.0
    assert reviews[0].property == "olympic-paddington"


def test_date_is_converted_to_sydney_local_date(payload):
    reviews = parse_reviews(payload, property_slug="olympic-paddington")

    # 1794865465 is 2026-11-16 21:44 UTC, which is already 17 Nov in Sydney (UTC+11)
    by_key = {r.review_key: r for r in reviews}
    assert str(by_key["86be75f8e32e4242"].review_date) == "2026-11-17"
    assert str(by_key["b5dd03c083f5278b"].review_date) == "2026-09-22"


def test_liked_and_disliked_text_are_kept_separate(payload):
    reviews = parse_reviews(payload, property_slug="olympic-paddington")

    first = reviews[0]
    assert first.liked == "The price and location were good."
    assert "sewerage" in first.disliked
    assert first.title == "Will not stay again."


def test_missing_title_becomes_none(payload):
    reviews = parse_reviews(payload, property_slug="olympic-paddington")

    by_key = {r.review_key: r for r in reviews}
    assert by_key["682d57bc349ad1f3"].title is None


def test_guest_and_stay_details(payload):
    reviews = parse_reviews(payload, property_slug="olympic-paddington")

    second = reviews[1]
    assert second.reviewer_country == "United Kingdom"
    assert second.traveller_type == "Solo traveller"
    assert second.room_type == "Superior Double Room (Ensuite)"
    assert second.nights == 4
    assert str(second.checkin_date) == "2026-08-30"
    assert second.language == "en"


def test_hotel_reply_is_decoded_and_missing_reply_is_none(payload):
    reviews = parse_reviews(payload, property_slug="olympic-paddington")

    by_key = {r.review_key: r for r in reviews}
    assert "We're glad" in by_key["cdea2877d7771ee9"].host_reply  # was "We&#39;re"
    assert by_key["86be75f8e32e4242"].host_reply is None
    assert by_key["86be75f8e32e4242"].has_host_reply is False
    assert by_key["b5dd03c083f5278b"].has_host_reply is True


def test_helpful_votes_are_kept(payload):
    reviews = parse_reviews(payload, property_slug="olympic-paddington")

    by_key = {r.review_key: r for r in reviews}
    assert by_key["682d57bc349ad1f3"].helpful_votes == 1


def test_reviewer_names_and_avatars_are_never_stored(payload):
    reviews = parse_reviews(payload, property_slug="olympic-paddington")

    dumped = json.dumps([r.model_dump(mode="json") for r in reviews])
    assert "TestGuest" not in dumped
    assert "avatar" not in dumped
    assert "username" not in dumped


from scraper.parse import ParseError, parse_page  # noqa: E402


def test_changed_layout_raises_parse_error():
    # Booking renamed the top-level key -> we must fail loudly, not return "no reviews"
    with pytest.raises(ParseError, match="layout"):
        parse_reviews({"data": {"somethingNew": {}}}, property_slug="olympic-paddington")


def test_empty_page_is_not_an_error(payload):
    # Paging past the last page legitimately returns no cards
    payload["data"]["reviewListFrontend"]["reviewCard"] = []

    assert parse_reviews(payload, property_slug="olympic-paddington") == []


def test_bad_review_is_quarantined_and_others_survive(payload):
    payload["data"]["reviewListFrontend"]["reviewCard"][1]["reviewScore"] = 11.0

    page = parse_page(payload, property_slug="olympic-paddington")

    assert len(page.reviews) == 4
    assert len(page.rejected) == 1
    assert page.rejected[0].review_key == "cdea2877d7771ee9"
    assert "rating" in page.rejected[0].reason


def test_page_reports_total_review_count_for_the_canary_check(payload):
    page = parse_page(payload, property_slug="olympic-paddington")

    assert page.reported_total == 133
