import html
import math
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from pydantic import ValidationError

from scraper.config import MAX_CARDS_PER_PAGE
from scraper.models import MAX_KEY_LEN, ParsedPage, RejectedReview, Review, clean_text

SYDNEY = ZoneInfo("Australia/Sydney")
_MIN_STAMP = datetime(2000, 1, 1, tzinfo=timezone.utc).timestamp()
_MAX_STAMP = datetime(2100, 1, 1, tzinfo=timezone.utc).timestamp()  # hard overflow guard; Review checks "not future"


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

    if len(cards) > MAX_CARDS_PER_PAGE:
        raise ParseError(f"Response carries {len(cards)} cards, more than the {MAX_CARDS_PER_PAGE} allowed per page")

    reviews: list[Review] = []
    rejected: list[RejectedReview] = []
    seen_keys: set[str] = set()
    for card in cards:
        try:
            review = _parse_card(card, property_slug)
            if review.review_key in seen_keys:
                raise ValueError("duplicate review_key on this page")
            seen_keys.add(review.review_key)
            reviews.append(review)
        except (ValidationError, KeyError, TypeError, ValueError, OverflowError, OSError) as exc:
            rejected.append(RejectedReview(review_key=_safe_key(card), reason=_short_reason(exc)))

    return ParsedPage(reviews=reviews, rejected=rejected, reported_total=_reported_total(result))


def _sydney_date(stamp) -> date:
    """Unix timestamp -> Sydney calendar date. Bounded first so hostile values cannot overflow datetime."""
    if isinstance(stamp, bool) or not isinstance(stamp, (int, float)) or not math.isfinite(stamp):
        raise ValueError(f"reviewedDate is not a finite number: {type(stamp).__name__}")
    if not (_MIN_STAMP <= stamp <= _MAX_STAMP):
        raise ValueError("reviewedDate timestamp is outside the plausible range")
    return datetime.fromtimestamp(stamp, SYDNEY).date()


def _section(parent: dict, name: str) -> dict:
    """An optional nested object. Absent/null is fine; any other non-object is a poisoned card."""
    value = parent.get(name)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise TypeError(f"{name} is {type(value).__name__}, expected an object")
    return value


def _parse_card(card: dict, property_slug: str) -> Review:
    if not isinstance(card, dict):
        raise TypeError(f"card is {type(card).__name__}, expected an object")
    text = _section(card, "textDetails")
    guest = _section(card, "guestDetails")
    booking = _section(card, "bookingDetails")
    room = _section(booking, "roomType")
    reply = _section(card, "partnerReply").get("reply")

    # Reviewer name and avatar are deliberately never read: personal data we do not need.
    return Review(
        review_key=card["reviewUrl"],
        property=property_slug,
        rating=card["reviewScore"],
        review_date=_sydney_date(card["reviewedDate"]),
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
        host_reply=html.unescape(reply) if isinstance(reply, str) and reply else (reply or None),
        helpful_votes=card.get("helpfulVotesCount") or 0,
    )


MAX_REPORTED_TOTAL = 10_000_000


def _reported_total(result: dict) -> int | None:
    """Booking's own total, used only for the canary check. Anything odd is ignored (None), never trusted."""
    options = result.get("reviewScoreFilter")
    if not isinstance(options, list):
        return None
    for option in options:
        if isinstance(option, dict) and option.get("value") == "ALL":
            count = option.get("count")
            if type(count) is int and 0 <= count <= MAX_REPORTED_TOTAL:
                return count
            return None
    return None


def _safe_key(card) -> str | None:
    key = card.get("reviewUrl") if isinstance(card, dict) else None
    return clean_text(key, MAX_KEY_LEN) if isinstance(key, str) else None


MAX_REASON_LEN = 300


def _short_reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        reason = "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
    else:
        reason = f"missing or malformed field: {exc!r}"
    return clean_text(reason, MAX_REASON_LEN)
