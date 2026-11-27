"""Data access and pure helpers for the dashboard. All metrics come from insights.metrics."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

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


def resolve_db_path() -> Path:
    raw = os.environ.get("REVIEWS_DB", "data/reviews.db")
    p = Path(raw)
    if p.is_absolute() or p.exists():
        return p
    return ROOT / p if (ROOT / p).exists() else p


def sydney_today() -> date:
    return datetime.now(SYDNEY).date()


@dataclass
class Bundle:
    reviews: pd.DataFrame
    topics: pd.DataFrame
    health: pd.DataFrame


@st.cache_data(show_spinner=False)
def _load_bundle(db_path: str, mtime: float) -> Bundle:
    """Cached on the DB file's modification time, so a fresh scrape shows up on the next refresh."""
    from insights import metrics
    return Bundle(metrics.load_reviews(db_path), metrics.load_topics(db_path), metrics.data_health(db_path))


def load_bundle(path: Path) -> Bundle:
    return _load_bundle(str(path), path.stat().st_mtime)


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
    for row in topics.itertuples(index=False):
        out.setdefault(row.review_key, []).append((row.topic, row.polarity, getattr(row, "evidence", "") or ""))
    for tags in out.values():
        tags.sort(key=lambda t: (t[1] != "negative", t[0]))
    return out


def _has_text(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().ne("")


def with_comment_mask(df: pd.DataFrame) -> pd.Series:
    """True where the guest wrote something (liked or disliked); False for rating-only reviews."""
    return _has_text(df["liked"]) | _has_text(df["disliked"])


def filter_feed(df: pd.DataFrame, chips: dict, *, topic_choice: str | None, only_negative: bool,
                no_reply: bool, search: str, sort: str, only_with_comment: bool = False) -> pd.DataFrame:
    out = df
    if only_with_comment:
        out = out[with_comment_mask(out)]
    if only_negative:
        out = out[out["band"] == "negative"]
    if no_reply:
        out = out[~out["has_reply"]]
    if topic_choice:  # "negative:noise" or "positive:location"
        pol, tid = topic_choice.split(":", 1)
        keep = {k for k, tags in chips.items() if any(t == tid and p == pol for t, p, _ in tags)}
        out = out[out["review_key"].isin(keep)]
    q = (search or "").strip().lower()
    if q:
        cols = ["title", "liked", "disliked", "host_reply", "room_type", "reviewer_country", "traveller_type",
                "property_name"]
        blob = out[cols].fillna("").astype(str).agg(" ".join, axis=1).str.lower()
        out = out[blob.str.contains(q, regex=False)]
    if sort == "Lowest score first":
        return out.sort_values(["rating", "review_date"], ascending=[True, False], kind="stable")
    return out.sort_values(["review_date", "rating"], ascending=[False, True], kind="stable")


def _safe_cell(v):
    """Stop spreadsheet formula injection: text starting with = + - @ is prefixed with an apostrophe."""
    if isinstance(v, str) and v[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + v
    return v


def feed_to_csv(df: pd.DataFrame, chips: dict, labels: dict[str, str]) -> bytes:
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
        out[c] = out[c].map(_safe_cell)
    return out.to_csv(index=False).encode("utf-8-sig")


def to_sydney(ts) -> str:
    """Format a stored timestamp as Sydney local time, or 'never' if missing."""
    if ts is None or (not isinstance(ts, str) and pd.isna(ts)):
        return "never"
    t = pd.to_datetime(ts, utc=True, errors="coerce")
    if pd.isna(t):
        return "unknown"
    return t.tz_convert(SYDNEY).strftime("%a %d %b %Y, %I:%M %p")
