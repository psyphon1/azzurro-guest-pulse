from datetime import date

from pydantic import BaseModel, Field


class Review(BaseModel):
    review_key: str
    property: str
    rating: float = Field(ge=1, le=10)
    review_date: date
    title: str | None = None
    liked: str | None = None
    disliked: str | None = None
    language: str | None = None
    reviewer_country: str | None = None
    traveller_type: str | None = None
    room_type: str | None = None
    nights: int | None = None
    checkin_date: date | None = None
    checkout_date: date | None = None
    host_reply: str | None = None
    helpful_votes: int = 0

    @property
    def has_host_reply(self) -> bool:
        return self.host_reply is not None


class RejectedReview(BaseModel):
    """A review card that failed validation. Kept so bad data is visible, not silently lost."""

    review_key: str | None
    reason: str


class ParsedPage(BaseModel):
    reviews: list[Review]
    rejected: list[RejectedReview]
    reported_total: int | None  # total review count Booking says exists, used for the canary check
