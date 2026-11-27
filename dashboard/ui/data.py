"""Data access and pure helpers for the dashboard. All metrics come from insights.metrics."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from dashboard.ui.privacy import looks_like_pii, mask_pii
from dashboard.ui.style import clean_text

SYDNEY = ZoneInfo("Australia/Sydney")
ROOT = Path(__file__).resolve().parents[2]

# Fixed IDs from docs/contracts.md. Used only if insights/topics.py cannot be imported.
_FALLBACK_TOPIC_LABELS = {
    "cleanliness": "Cleanliness", "check_in": "Check-in experience", "staff": "Staff behaviour",
    "noise": "Noise", "facilities": "Facilities", "location": "Location",
    "room_condition": "Room condition", "value": "Value for money",
}


def topic_labels() -> dict[str, str]:
    try:
        from insights.topics import TOPICS
        return {tid: t.label for tid, t in TOPICS.items()}
    except Exception:  # classifier module not available: fall back to the contract table
        return dict(_FALLBACK_TOPIC_LABELS)


LIVE_DB = Path("data") / "reviews.db"
SAMPLE_DB = Path("data") / "sample" / "reviews_sample.db"


def resolve_db_path() -> Path:
    """Which database file the dashboard reads.

    1. env REVIEWS_DB (blank counts as not set): used as given, even if it does not exist, so a typo is reported
       instead of being quietly replaced by other data (relative paths: working directory first, then project root).
    2. otherwise <project root>/data/reviews.db if it is a file (the live scrape),
    3. otherwise <project root>/data/sample/reviews_sample.db if it is a file (the committed public snapshot),
    4. otherwise the live default, which does not exist: the page then shows its friendly "no data" message.

    The defaults hang off the project root, never the working directory, so a server started from another folder
    cannot pick up somebody else's data/ folder.
    """
    raw = (os.environ.get("REVIEWS_DB") or "").strip()
    if raw:
        p = Path(raw)
        if p.is_absolute() or p.exists():
            return p
        return ROOT / p if (ROOT / p).exists() else p
    for candidate in (ROOT / LIVE_DB, ROOT / SAMPLE_DB):
        if candidate.is_file():
            return candidate
    return ROOT / LIVE_DB


def is_sample(path: Path) -> bool:
    """True for the public snapshot: "sample" in the file name, or in the name of the file a link points to."""
    names = [Path(path).name]
    try:
        names.append(Path(path).resolve().name)
    except (OSError, RuntimeError, ValueError):
        pass
    return any("sample" in n.lower() for n in names)


def sample_banner_text(health: pd.DataFrame | None) -> str:
    """The warning shown on a snapshot. The date is the last successful scrape recorded in the file, or 'unknown'."""
    when = "unknown"
    try:
        if health is not None and "last_ok_at" in health.columns and not health.empty:
            latest = pd.to_datetime(health["last_ok_at"], utc=True, errors="coerce").max()
            if pd.notna(latest):
                when = latest.tz_convert(SYDNEY).strftime("%d %b %Y")
    except (ValueError, TypeError, OverflowError):
        pass
    return f"SAMPLE DATA: a snapshot of real public Booking.com reviews, not live. Collected on {when}."


def sydney_today() -> date:
    return datetime.now(SYDNEY).date()


REQUIRED_REVIEW_COLUMNS = ("review_key", "property", "rating", "review_date", "title", "liked", "disliked",
                           "language", "reviewer_country", "traveller_type", "room_type", "host_reply")
FIRST_PLAUSIBLE_DATE = date(2000, 1, 1)
FUTURE_SLACK = timedelta(days=2)       # reviews are Sydney dates: allow for the time-zone difference only


class NotAReviewDatabase(Exception):
    """The file opened as SQLite but does not have the review columns."""


def clean_reviews(df: pd.DataFrame, today: date | None = None) -> tuple[pd.DataFrame, int]:
    """Drop rows that cannot be real reviews and say how many: unreadable date, date before 2000 or in the
    future, score missing or outside 1 to 10. One poisoned row (say, a review dated 2099) must not decide
    which week the whole dashboard calls 'the latest'."""
    today = today or sydney_today()
    ok = (df["review_date"].notna()
          & (df["review_date"] >= pd.Timestamp(FIRST_PLAUSIBLE_DATE))
          & (df["review_date"] <= pd.Timestamp(today + FUTURE_SLACK))
          & df["rating"].between(1, 10))
    return df[ok], int((~ok).sum())


def clean_topics(topics: pd.DataFrame, reviews: pd.DataFrame) -> pd.DataFrame:
    """Keep only tags the classifier could have written: a known topic, a known polarity, a stored review."""
    if topics is None or topics.empty:
        return topics
    ok = (topics["topic"].isin(topic_labels().keys()) & topics["polarity"].isin(["positive", "negative"])
          & topics["review_key"].isin(reviews["review_key"]))
    out = topics[ok].copy()
    if "evidence" in out.columns:
        out["evidence"] = out["evidence"].map(lambda v: clean_text(v, 500) if isinstance(v, str) else "")
    return out


@dataclass
class Bundle:
    reviews: pd.DataFrame
    topics: pd.DataFrame
    health: pd.DataFrame


def _signature(path: Path) -> tuple:
    """Size and modification time (nanoseconds) of the database AND its write-ahead log: a scrape in WAL mode
    changes the -wal file while the main file stays untouched, and a copy-over can keep the old timestamp."""
    sig = []
    for p in (path, path.with_name(path.name + "-wal")):
        try:
            st_ = p.stat()
            sig.append((st_.st_size, st_.st_mtime_ns))
        except OSError:
            sig.append(None)
    return tuple(sig)


@st.cache_data(show_spinner=False, ttl=300, max_entries=4)
def _load_bundle(db_path: str, signature: tuple) -> Bundle:
    """Cached on the file path plus its size/time signature (and at most 5 minutes), so a fresh scrape shows up
    on the next refresh and nothing is served stale or from a different file."""
    from insights import metrics
    reviews = metrics.load_reviews(db_path)
    missing = [c for c in REQUIRED_REVIEW_COLUMNS if c not in reviews.columns]
    if missing:
        raise NotAReviewDatabase(f"missing columns: {', '.join(missing)}")
    return Bundle(reviews, metrics.load_topics(db_path), metrics.data_health(db_path))


def load_bundle(path: Path) -> Bundle:
    return _load_bundle(str(path), _signature(path))


# --- date presets -----------------------------------------------------------------------------
PRESETS = ["Latest full week", "This week so far", "Last week", "Last 4 weeks", "Last 12 weeks", "All time",
           "Custom dates"]


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def preset_range(preset: str, latest_week: date, today: date, first: date, last: date,
                 custom: tuple[date, date] | None = None) -> tuple[date, date, date]:
    """Return (start, end, focus_week). `focus_week` is the Monday the week-level sections describe."""
    this_monday = monday_of(today)
    if preset == "This week so far":
        return this_monday, this_monday + timedelta(days=6), this_monday
    if preset == "Last week":
        w = this_monday - timedelta(days=7)
        return w, w + timedelta(days=6), w
    if preset == "Last 4 weeks":
        return latest_week - timedelta(weeks=3), latest_week + timedelta(days=6), latest_week
    if preset == "Last 12 weeks":
        return latest_week - timedelta(weeks=11), latest_week + timedelta(days=6), latest_week
    if preset == "All time":
        return first, max(last, latest_week + timedelta(days=6)), latest_week
    if preset == "Custom dates" and custom:
        s, e = custom
        if e < s:
            s, e = e, s
        return s, e, monday_of(min(e, today))
    return latest_week, latest_week + timedelta(days=6), latest_week  # Latest full week (default)


def nice_range(start: date, end: date) -> str:
    return f"{start.strftime('%a %d %b')} to {end.strftime('%a %d %b %Y')}"


# --- review feed ------------------------------------------------------------------------------
def topic_chips(topics: pd.DataFrame) -> dict[str, list[tuple[str, str, str]]]:
    """review_key -> [(topic_id, polarity, evidence)], complaints first."""
    out: dict[str, list[tuple[str, str, str]]] = {}
    if topics is None or topics.empty:
        return out
    evidence = topics["evidence"] if "evidence" in topics.columns else pd.Series([""] * len(topics))
    # .tolist() once per column: iterating a pandas (Arrow) column cell by cell is many times slower.
    for key, topic, pol, ev in zip(topics["review_key"].tolist(), topics["topic"].tolist(),
                                   topics["polarity"].tolist(), evidence.tolist()):
        out.setdefault(key, []).append((topic, pol, ev if isinstance(ev, str) else ""))
    for tags in out.values():
        tags.sort(key=lambda t: (t[1] != "negative", t[0]))
    return out


def _has_text(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().ne("")


def with_comment_mask(df: pd.DataFrame) -> pd.Series:
    """True where the guest wrote something (liked or disliked); False for rating-only reviews."""
    return _has_text(df["liked"]) | _has_text(df["disliked"])


MAX_SEARCH_CHARS = 200       # longer search text is cut off: nobody types a 10 MB search, an attacker might


def parse_topic_choice(choice, known: dict | None = None) -> tuple[str, str] | None:
    """'negative:noise' -> ('negative', 'noise'); anything malformed or unknown -> None (filter ignored)."""
    if not isinstance(choice, str) or choice.count(":") != 1:
        return None
    pol, tid = choice.split(":")
    if pol not in ("positive", "negative") or not tid or (known is not None and tid not in known):
        return None
    return pol, tid


def clamp_page(raw, pages: int) -> int:
    """A page number from untrusted session state, forced into 1..pages (garbage becomes page 1)."""
    try:
        page = int(raw)
    except (TypeError, ValueError, OverflowError):
        page = 1
    return min(max(1, page), max(1, pages))


def filter_feed(df: pd.DataFrame, chips: dict, *, topic_choice: str | None, only_negative: bool,
                no_reply: bool, search: str, sort: str, only_with_comment: bool = False) -> pd.DataFrame:
    out = df
    if only_with_comment:
        out = out[with_comment_mask(out)]
    if only_negative:
        out = out[out["band"] == "negative"]
    if no_reply:
        out = out[~out["has_reply"]]
    parsed = parse_topic_choice(topic_choice)
    if parsed:  # "negative:noise" or "positive:location"
        pol, tid = parsed
        keep = {k for k, tags in chips.items() if any(t == tid and p == pol for t, p, _ in tags)}
        out = out[out["review_key"].isin(keep)]
    q = str(search or "")[:MAX_SEARCH_CHARS].strip().lower()   # literal text, never a pattern (regex=False below)
    if q and looks_like_pii(q):     # never confirm that some review contains a given email address or number
        return out.iloc[0:0]
    if q:
        cols = ["title", "liked", "disliked", "host_reply", "room_type", "reviewer_country", "traveller_type",
                "property_name"]
        hit = pd.Series(False, index=out.index)
        for col in cols:      # one vectorised literal scan per column: far faster than joining text row by row
            hit |= out[col].fillna("").astype(str).str.lower().str.contains(q, regex=False)
        out = out[hit]
    if sort == "Lowest score first":
        return out.sort_values(["rating", "review_date"], ascending=[True, False], kind="stable")
    return out.sort_values(["review_date", "rating"], ascending=[False, True], kind="stable")


MAX_EXPORT_ROWS = 50_000     # the CSV never has more rows than this; the page says so when it cuts
MAX_CELL_CHARS = 30_000      # Excel refuses cells above 32,767 characters
_FORMULA_CHARS = frozenset("=+-@\uff1d\uff0b\uff0d\uff20")   # ASCII and full-width forms
_LEADING_BLANKS = " \t\r\n\v\f\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u200b\u2028\u2029\u202f\u205f\u2060\u3000\ufeff"


def _safe_cell(v):
    """Stop spreadsheet formula injection (OWASP 'CSV injection').

    Excel, LibreOffice and Google Sheets treat a cell as a formula when its first non-blank character is
    `=`, `+`, `-` or `@` (also after leading spaces, tabs or line breaks, and in full-width form). Such text
    gets a leading apostrophe, which spreadsheets show as plain text. Non-text values (scores) are untouched.
    """
    if isinstance(v, str) and v.lstrip(_LEADING_BLANKS)[:1] in _FORMULA_CHARS:
        return "'" + v
    return v


def _export_cell(v):
    """One text cell of the export: hidden characters removed, shortened, then formula-proofed."""
    if not isinstance(v, str):
        return v
    return _safe_cell(mask_pii(clean_text(v, MAX_CELL_CHARS)))


def feed_to_csv_limited(df: pd.DataFrame, chips: dict, labels: dict[str, str],
                        max_rows: int | None = None) -> tuple[bytes, int]:
    """CSV bytes for at most `max_rows` rows (default MAX_EXPORT_ROWS), and how many rows were written."""
    limit = MAX_EXPORT_ROWS if max_rows is None else max_rows
    df = df.iloc[:limit]

    def names(key, pol):
        return "; ".join(labels.get(t, t) for t, p, _ in chips.get(key, []) if p == pol)

    out = pd.DataFrame({
        "Date": df["review_date"].dt.strftime("%Y-%m-%d"),
        "Hotel": df["property_name"],
        "Score": df["rating"],
        "Room": df["room_type"],
        "Traveller type": df["traveller_type"],
        "Country": df["reviewer_country"],
        "Title": df["title"],
        "What guests liked": df["liked"],
        "What guests disliked": df["disliked"],
        "Hotel reply": df["host_reply"],
        "Complaint topics": [names(k, "negative") for k in df["review_key"]],
        "Praise topics": [names(k, "positive") for k in df["review_key"]],
    })
    text_cols = out.select_dtypes(include=["object", "string"]).columns
    for c in text_cols:
        out[c] = out[c].map(_export_cell)
    return out.to_csv(index=False).encode("utf-8-sig"), len(out)


def feed_to_csv(df: pd.DataFrame, chips: dict, labels: dict[str, str]) -> bytes:
    return feed_to_csv_limited(df, chips, labels)[0]


def to_sydney(ts) -> str:
    """Format a stored timestamp as Sydney local time, or 'never' if missing."""
    if ts is None or (not isinstance(ts, str) and pd.isna(ts)):
        return "never"
    t = pd.to_datetime(ts, utc=True, errors="coerce")
    if pd.isna(t):
        return "unknown"
    return t.tz_convert(SYDNEY).strftime("%a %d %b %Y, %I:%M %p")


# --- hotels with no reviews ------------------------------------------------------------------------
@dataclass(frozen=True)
class NoData:
    """A hotel the dashboard has no usable reviews for, and the plain-English reason why."""
    slug: str
    name: str
    reason: str          # one plain sentence for staff
    detail: str = ""     # the ledger's own words (already free of angle brackets), may be empty


def no_data_reason(status, error, stored: int) -> tuple[str, str]:
    """(plain-English reason, ledger detail) for a hotel that has no usable reviews. Never raises."""
    detail = ""
    if isinstance(error, str) and error.strip():
        from dashboard.ui.style import plain_text
        detail = plain_text(error)
    if stored:
        return ("Some reviews are stored, but none could be used because their dates or scores could not be trusted.", detail)
    reasons = {
        "blocked": "Booking.com blocked our automatic check, so no reviews could be collected.",
        "failed": "The last attempt to collect reviews failed, so none are stored.",
        "interrupted": "The last attempt to collect reviews was cut short before any were saved.",
        "running": "Collection is running now. Reviews should appear after it finishes.",
        "ok": "The last collection finished but found no reviews for this hotel.",
    }
    never = "Reviews have never been collected for this hotel."
    return (reasons.get(status, never) if isinstance(status, str) else never), detail


def hotels_without_reviews(health: pd.DataFrame | None, reviews: pd.DataFrame | None = None) -> dict[str, NoData]:
    """slug -> NoData for every hotel in the health table with no usable review (not in `reviews`, or, without
    `reviews`, with nothing stored). Built only from the DataFrames insights.metrics returned."""
    out: dict[str, NoData] = {}
    if health is None or health.empty:
        return out
    have = set(reviews["property"]) if reviews is not None and not reviews.empty else set()
    for r in health.itertuples(index=False):
        stored = int(r.stored) if pd.notna(r.stored) else 0
        usable = r.property in have if reviews is not None else stored > 0
        if usable:
            continue
        status = r.latest_status if isinstance(r.latest_status, str) else None
        reason, detail = no_data_reason(status, r.latest_error, stored)
        out[r.property] = NoData(r.property, r.property_name, reason, detail)
    return out
