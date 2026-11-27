import re
from datetime import date, datetime, timedelta, timezone

from pydantic import BaseModel, Field, field_validator, model_validator

# Plausibility window for dates. Booking.com reviews cannot predate the site's review feature, and a review
# cannot be written in the future (2 days of slack for Sydney being ahead of UTC and clock skew).
MIN_DATE = date(2000, 1, 1)
FUTURE_SLACK = timedelta(days=2)
MAX_NIGHTS = 365
MAX_VOTES = 1_000_000


MAX_TEXT = 5000       # liked / disliked / title / host reply: longer text is truncated (with an ellipsis)
MAX_SHORT = 200       # country, traveller type, room name
MAX_KEY_LEN = 128
KEY_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}")   # Booking ids are short hex strings
SLUG_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
LANG_RE = re.compile(r"[A-Za-z]{2,3}(?:[-_][A-Za-z0-9]{2,8})?")

# Invisible or terminal-active characters: C0/C1 controls (keeps \n and \t), DEL, lone surrogates, noncharacters,
# bidi embeddings/overrides/isolates (Trojan Source), zero-width space/non-joiner, word joiner, BOM.
# Zero-width JOINER (U+200D) is kept so emoji sequences are not broken.
_STRIP = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\ud800-\udfff\ufffe\uffff"
                    "\u200b\u200c\u200e\u200f\u202a-\u202e\u2060\u2066-\u2069\ufeff]")
_LINE_BREAKS = re.compile("[\r\n\u2028\u2029\t]+")


def clean_text(value: str, limit: int, multiline: bool = False) -> str:
    """Make attacker-controlled text safe to store and display: strip invisible/terminal-active characters,
    normalise line endings, and truncate to ``limit`` characters (marked with an ellipsis)."""
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\u2028", "\n").replace("\u2029", "\n")
    value = _STRIP.sub("", value)
    if not multiline:
        value = _LINE_BREAKS.sub(" ", value).strip()
    if len(value) > limit:
        value = value[: limit - 1] + "…"
    return value


def latest_plausible_date() -> date:
    return (datetime.now(timezone.utc) + FUTURE_SLACK).date()


def _reject_bool(value):
    """bool is an int subclass: True would silently become rating 1.0 / 1 night / 1 vote."""
    if isinstance(value, bool):
        raise ValueError("a boolean is not a number")
    return value


def _check_date(value: date | None, label: str) -> date | None:
    if value is not None and not (MIN_DATE <= value <= latest_plausible_date()):
        raise ValueError(f"{label} {value} is outside the plausible window {MIN_DATE}..{latest_plausible_date()}")
    return value


class Review(BaseModel):
    review_key: str
    property: str
    rating: float = Field(ge=1, le=10, allow_inf_nan=False)
    review_date: date
    title: str | None = None
    liked: str | None = None
    disliked: str | None = None
    language: str | None = None
    reviewer_country: str | None = None
    traveller_type: str | None = None
    room_type: str | None = None
    nights: int | None = Field(default=None, ge=0, le=MAX_NIGHTS)
    checkin_date: date | None = None
    checkout_date: date | None = None
    host_reply: str | None = None
    helpful_votes: int = Field(default=0, ge=0, le=MAX_VOTES)

    @field_validator("review_key")
    @classmethod
    def _key_is_strict(cls, v):
        if not KEY_RE.fullmatch(v):
            raise ValueError("review_key must match [A-Za-z0-9][A-Za-z0-9._:~-]{0,127}")
        return v

    @field_validator("property")
    @classmethod
    def _slug_is_strict(cls, v):
        if not SLUG_RE.fullmatch(v):
            raise ValueError("property must be a lowercase slug")
        return v

    @field_validator("liked", "disliked")
    @classmethod
    def _long_text(cls, v):
        return None if v is None else clean_text(v, MAX_TEXT, multiline=True)

    @field_validator("host_reply")
    @classmethod
    def _reply(cls, v):
        """NULL means 'no reply yet' to the dashboard. Text that is empty once invisible characters are removed
        must not be able to fake a reply (and hide a review from the unreplied list)."""
        if v is None:
            return None
        v = clean_text(v, MAX_TEXT, multiline=True)
        return v if v.replace("\ufffd", "").strip() else None

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        return None if v is None else clean_text(v, MAX_TEXT)

    @field_validator("reviewer_country", "traveller_type", "room_type")
    @classmethod
    def _short_text(cls, v):
        return None if v is None else clean_text(v, MAX_SHORT)

    @field_validator("language")
    @classmethod
    def _language_code(cls, v):
        return v if v is not None and LANG_RE.fullmatch(v) else None

    @field_validator("rating", "nights", "helpful_votes", mode="before")
    @classmethod
    def _numbers_are_not_booleans(cls, v):
        return _reject_bool(v)

    @field_validator("review_date")
    @classmethod
    def _review_date_plausible(cls, v):
        return _check_date(v, "review_date")

    @field_validator("checkin_date", "checkout_date")
    @classmethod
    def _stay_dates_plausible(cls, v):
        return _check_date(v, "stay date")

    @model_validator(mode="after")
    def _stay_is_ordered(self):
        if self.checkin_date and self.checkout_date and self.checkout_date < self.checkin_date:
            raise ValueError("checkout_date is before checkin_date")
        return self

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
