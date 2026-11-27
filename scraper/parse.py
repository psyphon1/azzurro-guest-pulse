import html
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from scraper.models import ParsedPage, RejectedReview, Review

SYDNEY = ZoneInfo("Australia/Sydney")


class ParseError(Exception):
    """The response does not look like a review list. Usually means Booking changed its layout."""


def parse_reviews(payload: dict, property_slug: str) -> list[Review]:
    return parse_page(payload, property_slug).reviews


def parse_page(payload: dict, property_slug: str) -> ParsedPage:
    try:
        result = payload["data"]["reviewListFrontend"]
        cards = result["reviewCard"]
    except (KeyError, TypeError) as exc:
        raise ParseError("Unexpected response shape: review list layout probably changed") from exc
    if not isinstance(cards, list):
        raise ParseError("Unexpected response shape: reviewCard is not a list, layout probably changed")

    reviews: list[Review] = []
    rejected: list[RejectedReview] = []
    for card in cards:
        try:
            reviews.append(_parse_card(card, property_slug))
        except (ValidationError, KeyError, TypeError) as exc:
            rejected.append(RejectedReview(review_key=_safe_key(card), reason=_short_reason(exc)))

    return ParsedPage(reviews=reviews, rejected=rejected, reported_total=_reported_total(result))


def _parse_card(card: dict, property_slug: str) -> Review:
    text = card.get("textDetails") or {}
    guest = card.get("guestDetails") or {}
    booking = card.get("bookingDetails") or {}
    room = booking.get("roomType") or {}
    reply = (card.get("partnerReply") or {}).get("reply")

    # Reviewer name and avatar are deliberately never read: personal data we do not need.
    return Review(
        review_key=card["reviewUrl"],
        property=property_slug,
        rating=card["reviewScore"],
        review_date=datetime.fromtimestamp(card["reviewedDate"], SYDNEY).date(),
        title=text.get("title"),
        liked=text.get("positiveText"),
        disliked=text.get("negativeText"),
        language=text.get("lang"),
        reviewer_country=guest.get("countryName"),
        traveller_type=guest.get("guestTypeTranslation"),
        room_type=room.get("name"),
        nights=booking.get("numNights"),
        checkin_date=booking.get("checkinDate"),
        checkout_date=booking.get("checkoutDate"),
        host_reply=html.unescape(reply) if reply else None,
        helpful_votes=card.get("helpfulVotesCount") or 0,
    )


def _reported_total(result: dict) -> int | None:
    for option in result.get("reviewScoreFilter") or []:
        if option.get("value") == "ALL":
            return option.get("count")
    return None


def _safe_key(card) -> str | None:
    return card.get("reviewUrl") if isinstance(card, dict) else None


def _short_reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
    return f"missing or malformed field: {exc!r}"
