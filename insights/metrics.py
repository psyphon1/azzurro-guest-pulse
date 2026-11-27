"""Metrics and auto-generated insights (module 2).

Pure functions: no Streamlit, no printing, no network. Weeks are Monday-Sunday (Sydney); a week is
identified by its Monday date. ``review_date`` in the database is already Sydney local.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from scraper.config import BY_SLUG

POSITIVE_FROM = 8.0
NEGATIVE_BELOW = 5.0
LOW_SAMPLE_BELOW = 5


def sentiment_band(rating: float) -> str:
    """The one place sentiment bands are defined: >=8 positive, 5 to <8 mixed, <5 negative."""
    if rating is None or pd.isna(rating):
        raise ValueError("rating is missing")
    if rating >= POSITIVE_FROM:
        return "positive"
    if rating >= NEGATIVE_BELOW:
        return "mixed"
    return "negative"


def _as_date(d) -> date:
    if isinstance(d, (datetime, pd.Timestamp)):
        return d.date()
    if isinstance(d, str):
        return date.fromisoformat(d[:10])
    return d


def week_start_of(d: date) -> date:
    d = _as_date(d)
    return d - timedelta(days=d.weekday())


def latest_complete_week(df, today: date | None = None) -> date | None:
    """Monday of the most recent fully elapsed Mon-Sun week that contains data.

    "Elapsed" is judged against ``today`` if given, else the newest review date in ``df`` (so the
    result does not depend on the wall clock). A week is complete only once its Sunday is before
    that reference day. If the data only covers the current unfinished week, that week is returned.
    None for an empty frame.
    """
    if df is None or len(df) == 0:
        return None
    dates = pd.to_datetime(df["review_date"], errors="coerce").dropna().dt.date
    if len(dates) == 0:
        return None
    newest = max(dates)
    ref = _as_date(today) if today is not None else newest
    weeks = {week_start_of(d) for d in dates}
    complete = [w for w in weeks if w + timedelta(days=6) < ref]
    return max(complete) if complete else week_start_of(newest)


# ---------------------------------------------------------------------------- loading
REVIEW_COLUMNS = [
    "review_key", "property", "rating", "review_date", "title", "liked", "disliked", "language",
    "reviewer_country", "traveller_type", "room_type", "nights", "checkin_date", "checkout_date",
    "host_reply", "helpful_votes", "content_hash", "first_seen", "last_seen", "missing_since",
]
TOPIC_COLUMNS = ["review_key", "topic", "polarity", "evidence", "method", "taxonomy_version"]


def _band_or_none(rating) -> str | None:
    return None if rating is None or pd.isna(rating) else sentiment_band(rating)


def _prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with review_date as datetime64 and the derived columns present.

    Safe to call on frames that already have them (loaders) or on minimal frames (tests, callers).
    """
    out = df.copy()
    for col in ("review_key", "property", "rating", "review_date", "host_reply"):
        if col not in out.columns:
            out[col] = pd.Series(dtype="object")
    dates = pd.to_datetime(out["review_date"], errors="coerce")
    # A date nobody could have written (year 1, year 9999) is treated as unknown rather than overflowing later.
    out["review_date"] = dates.where((dates >= pd.Timestamp("1900-01-01")) & (dates <= pd.Timestamp("2200-01-01")))
    out["rating"] = pd.to_numeric(out["rating"], errors="coerce")
    if "week_start" not in out.columns:
        out["week_start"] = [
            None if pd.isna(d) else d.date() - timedelta(days=d.weekday()) for d in out["review_date"]
        ]
    if "band" not in out.columns:
        out["band"] = [_band_or_none(r) for r in out["rating"]]
    if "has_reply" not in out.columns:
        out["has_reply"] = out["host_reply"].map(
            lambda v: isinstance(v, str) and v.strip() != "").astype(bool)
    if "property_name" not in out.columns:
        out["property_name"] = out["property"].map(_name)
    return out


_ALLOWED_ACTIONS = frozenset({sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION,
                              sqlite3.SQLITE_RECURSIVE})


def _read_only_authorizer(action, *_):
    """Allow reading rows and nothing else: no writes, no ATTACH (which would create a file), no PRAGMA."""
    return sqlite3.SQLITE_OK if action in _ALLOWED_ACTIONS else sqlite3.SQLITE_DENY


def _connect_ro(db_path) -> sqlite3.Connection:
    """Open read-only so a wrong path raises instead of silently creating an empty database.

    The path is percent-encoded by Path.as_uri(), so a name such as ``x.db?mode=rwc`` stays a file NAME and
    cannot add URI parameters. On top of mode=ro, an authorizer refuses everything except reading.
    """
    if str(db_path) == ":memory:":
        return sqlite3.connect(":memory:")
    con = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    con.execute("PRAGMA query_only = ON")
    con.set_authorizer(_read_only_authorizer)
    return con


def _read(db_path, sql: str, columns: list[str]) -> pd.DataFrame:
    """Run one literal SELECT. A missing table gives an empty frame; any other problem (not a database,
    corrupt, unreadable) is raised so the caller can tell the user, instead of looking like 'no data'."""
    con = _connect_ro(db_path)
    try:
        try:
            return pd.read_sql_query(sql, con)
        except (pd.errors.DatabaseError, sqlite3.OperationalError) as exc:
            if "no such table" in str(exc).lower() or "no such column" in str(exc).lower():
                return pd.DataFrame({c: pd.Series(dtype="object") for c in columns})
            raise
    finally:
        con.close()


def load_reviews(db_path) -> pd.DataFrame:
    """All reviews (including ones flagged missing_since), with week_start, band, has_reply, property_name."""
    df = _read(db_path, "SELECT * FROM reviews", REVIEW_COLUMNS)
    return _prepare(df)


def load_topics(db_path) -> pd.DataFrame:
    """review_topics rows; an empty frame with the right columns if the table does not exist yet."""
    return _read(db_path, "SELECT * FROM review_topics", TOPIC_COLUMNS)


# ---------------------------------------------------------------------------- weekly numbers
@dataclass(frozen=True)
class WeekSummary:
    week_start: date
    n: int
    avg_rating: float | None
    positive: int
    mixed: int
    negative: int


@dataclass(frozen=True)
class WeekComparison:
    current: WeekSummary
    previous: WeekSummary
    delta: float | None          # current avg minus previous avg; None if either week has no reviews


def _window(df: pd.DataFrame, start, end, properties=None) -> pd.DataFrame:
    """Reviews with start <= review_date <= end (inclusive dates), optionally for some properties."""
    d = _prepare(df)
    s, e = pd.Timestamp(_as_date(start)), pd.Timestamp(_as_date(end))
    d = d[(d["review_date"] >= s) & (d["review_date"] <= e)]
    if properties is not None:
        d = d[d["property"].isin(list(properties))]
    return d


def _week_window(df, week_start, properties=None) -> pd.DataFrame:
    ws = week_start_of(week_start)
    return _window(df, ws, ws + timedelta(days=6), properties)


def _summarise(rows: pd.DataFrame, ws: date) -> WeekSummary:
    n = len(rows)
    bands = rows["band"].value_counts()
    return WeekSummary(
        week_start=ws, n=n,
        avg_rating=float(rows["rating"].mean()) if n else None,
        positive=int(bands.get("positive", 0)), mixed=int(bands.get("mixed", 0)),
        negative=int(bands.get("negative", 0)),
    )


def week_summary(df, week_start, properties=None) -> WeekSummary:
    ws = week_start_of(week_start)
    return _summarise(_week_window(df, ws, properties), ws)


def compare_weeks(df, week_start, properties=None) -> WeekComparison:
    ws = week_start_of(week_start)
    cur = week_summary(df, ws, properties)
    prev = week_summary(df, ws - timedelta(days=7), properties)
    delta = None
    if cur.avg_rating is not None and prev.avg_rating is not None:
        delta = cur.avg_rating - prev.avg_rating
    return WeekComparison(current=cur, previous=prev, delta=delta)


BREAKDOWN_COLUMNS = ["property", "property_name", "avg_rating", "n", "prev_avg", "prev_n", "delta", "low_sample"]


def property_breakdown(df, week_start) -> pd.DataFrame:
    ws = week_start_of(week_start)
    d = _prepare(df)
    rows = []
    for prop in sorted(d["property"].dropna().unique(), key=lambda p: (_name(p), p)):
        c = compare_weeks(d, ws, [prop])
        rows.append({
            "property": prop, "property_name": _name(prop),
            "avg_rating": c.current.avg_rating if c.current.n else float("nan"), "n": c.current.n,
            "prev_avg": c.previous.avg_rating if c.previous.n else float("nan"), "prev_n": c.previous.n,
            "delta": c.delta if c.delta is not None else float("nan"),
            "low_sample": c.current.n < LOW_SAMPLE_BELOW,
        })
    return pd.DataFrame(rows, columns=BREAKDOWN_COLUMNS)


_UNSAFE_NAME_CHARS = re.compile(r"[^\w .\-()']")
MAX_NAME_CHARS = 60


def safe_label(value, fallback: str = "Unknown") -> str:
    """A database-supplied name made safe to show anywhere (HTML, chart labels, widgets, tables).

    Only letters, digits, spaces and a few quiet symbols survive, so markup, links and control characters
    cannot get through. Capped at 60 characters.
    """
    text = _UNSAFE_NAME_CHARS.sub("", str(value)) if value is not None else ""
    text = " ".join(text.split())[:MAX_NAME_CHARS].strip()
    return text or fallback


def _name(slug: str) -> str:
    return BY_SLUG[slug].name if slug in BY_SLUG else safe_label(slug, "Unknown hotel")


TREND_COLUMNS = ["week_start", "n", "avg_rating", "positive", "mixed", "negative"]


MAX_TREND_WEEKS = 520     # ten years; a tampered date range cannot make the trend loop over millennia


def weekly_trend(df, start, end, properties=None) -> pd.DataFrame:
    """One row per Mon-Sun week from the week of ``start`` to the week of ``end``; empty weeks have n=0.

    At most MAX_TREND_WEEKS weeks are returned (the newest ones). One pass over the data, not one per week.
    """
    d = _prepare(df)
    first, last = week_start_of(start), week_start_of(end)
    first = max(first, last - timedelta(weeks=MAX_TREND_WEEKS - 1))
    d = d[(d["review_date"] >= pd.Timestamp(first)) & (d["review_date"] <= pd.Timestamp(last + timedelta(days=6)))]
    if properties is not None:
        d = d[d["property"].isin(list(properties))]
    weeks = d["week_start"].tolist()
    ratings = d["rating"].tolist()
    bands = d["band"].tolist()
    acc: dict = {}
    for wk, rating, band in zip(weeks, ratings, bands):
        slot = acc.setdefault(wk, [0, 0.0, 0, {"positive": 0, "mixed": 0, "negative": 0}])
        slot[0] += 1
        if rating == rating:           # a missing score (NaN) counts as a review but not towards the average
            slot[1] += rating
            slot[2] += 1
        if band in slot[3]:
            slot[3][band] += 1
    rows = []
    w = first
    while w <= last:
        n, total, rated, counts = acc.get(w, (0, 0.0, 0, {"positive": 0, "mixed": 0, "negative": 0}))
        rows.append({
            "week_start": w, "n": n, "avg_rating": total / rated if rated else float("nan"),
            "positive": counts["positive"], "mixed": counts["mixed"], "negative": counts["negative"],
        })
        w += timedelta(days=7)
    return pd.DataFrame(rows, columns=TREND_COLUMNS)


# ---------------------------------------------------------------------------- topics
_FALLBACK_TOPIC_LABELS = {
    "cleanliness": "Cleanliness", "check_in": "Check-in experience", "staff": "Staff behaviour",
    "noise": "Noise", "facilities": "Facilities", "location": "Location",
    "room_condition": "Room condition", "value": "Value for money",
}


def _topic_labels() -> dict[str, str]:
    """id -> label. Prefers insights.topics.TOPICS (looked up lazily; may not exist yet)."""
    try:
        from insights.topics import TOPICS   # noqa: PLC0415
        return {tid: t.label for tid, t in TOPICS.items()}
    except Exception:
        return dict(_FALLBACK_TOPIC_LABELS)


SHARE_COLUMNS = ["topic", "label", "count", "n_reviews", "share", "low_sample", "n_band_total"]
HEATMAP_COLUMNS = ["property", "property_name", "topic", "label", "count"]
_POLARITY_BAND = {"negative": "negative", "positive": "positive"}
_POLARITY_TEXT_COLUMN = {"negative": "disliked", "positive": "liked"}


def _has_text(d: pd.DataFrame, polarity: str) -> pd.Series:
    """True where the review has written text for this polarity (disliked for negative, liked for positive).

    Frames without that column (minimal frames) are treated as having text everywhere.
    """
    col = _POLARITY_TEXT_COLUMN[polarity]
    if col not in d.columns:
        return pd.Series(True, index=d.index)
    return d[col].map(lambda v: isinstance(v, str) and v.strip() != "").astype(bool)


def _is_non_english(lang) -> bool:
    return isinstance(lang, str) and lang.strip() != "" and not lang.strip().lower().startswith("en")


@dataclass(frozen=True)
class CommentCounts:
    n_band_total: int        # all reviews in the sentiment band (rating-only ones included)
    n_with_comment: int      # those with written text for the polarity: the denominator for topic shares
    n_without_comment: int
    n_non_english: int       # of n_with_comment, how many are not English (the keyword classifier is English-only)


def _tagged(df, topics, start, end, polarity, properties=None):
    """(band rows, band rows with written text, their distinct (review_key, topic) tags) for the window."""
    if polarity not in _POLARITY_BAND:
        raise ValueError(f"polarity must be 'positive' or 'negative', not {polarity!r}")
    band_rows = _window(df, start, end, properties)
    band_rows = band_rows[band_rows["band"] == _POLARITY_BAND[polarity]]
    text_rows = band_rows[_has_text(band_rows, polarity)]
    if topics is None or len(topics) == 0 or len(text_rows) == 0:
        return band_rows, text_rows, pd.DataFrame(
            {"review_key": pd.Series(dtype="object"), "topic": pd.Series(dtype="object")})
    tags = topics.loc[topics["polarity"] == polarity, ["review_key", "topic"]].drop_duplicates()
    return band_rows, text_rows, tags[tags["review_key"].isin(text_rows["review_key"])]


def comment_counts(df, start, end, polarity="negative", properties=None) -> CommentCounts:
    band_rows, text_rows, _ = _tagged(df, None, start, end, polarity, properties)
    if "language" in text_rows.columns:
        non_en = sum(1 for v in text_rows["language"] if _is_non_english(v))
    else:
        non_en = 0
    return CommentCounts(len(band_rows), len(text_rows), len(band_rows) - len(text_rows), non_en)


def topic_shares(df, topics, start, end, polarity="negative", properties=None) -> pd.DataFrame:
    """Per topic: reviews carrying the tag, out of reviews in the polarity's band that have written text.

    ``n_reviews`` is that denominator (negative uses reviews with a ``disliked`` text, positive ``liked``);
    ``n_band_total`` is every review in the band, including rating-only ones. Only topics with at least one
    tag are returned, most frequent first (ties by topic id).
    """
    band_rows, text_rows, tags = _tagged(df, topics, start, end, polarity, properties)
    n_reviews, n_band = len(text_rows), len(band_rows)
    labels = _topic_labels()
    counts = tags.groupby("topic").size()
    out = [{
        "topic": t, "label": labels.get(t, safe_label(t)), "count": int(c), "n_reviews": n_reviews,
        "share": (int(c) / n_reviews) if n_reviews else 0.0, "low_sample": n_reviews < LOW_SAMPLE_BELOW,
        "n_band_total": n_band,
    } for t, c in counts.items()]
    out.sort(key=lambda r: (-r["count"], r["topic"]))
    return pd.DataFrame(out, columns=SHARE_COLUMNS)


def topic_by_property(df, topics, start, end, polarity="negative") -> pd.DataFrame:
    """Heatmap grid: every property in df x every topic, count of reviews with that tag (zeros included)."""
    _, rows, tags = _tagged(df, topics, start, end, polarity)
    props = sorted(_prepare(df)["property"].dropna().unique(), key=lambda p: (_name(p), p))
    labels = _topic_labels()
    topic_ids = list(labels) + sorted(set(tags["topic"]) - set(labels))
    merged = tags.merge(rows[["review_key", "property"]], on="review_key")
    counts = merged.groupby(["property", "topic"]).size().to_dict()
    out = [{
        "property": p, "property_name": _name(p), "topic": t, "label": labels.get(t, safe_label(t)),
        "count": int(counts.get((p, t), 0)),
    } for p in props for t in topic_ids]
    return pd.DataFrame(out, columns=HEATMAP_COLUMNS)


# ---------------------------------------------------------------------------- unreplied
def unreplied_reviews(df, properties=None, max_age_days=None, band=None, as_of=None) -> pd.DataFrame:
    """Reviews with no hotel reply, newest first.

    ``max_age_days`` counts back from ``as_of`` (default: the newest review date in df, not the clock).
    ``band`` optionally restricts to one sentiment band (e.g. "negative").
    """
    d = _prepare(df)
    if properties is not None:
        d = d[d["property"].isin(list(properties))]
    d = d[~d["has_reply"].astype(bool)]
    if band is not None:
        d = d[d["band"] == band]
    if max_age_days is not None and len(d):
        ref = pd.Timestamp(_as_date(as_of)) if as_of is not None else _prepare(df)["review_date"].max()
        d = d[d["review_date"] >= ref - pd.Timedelta(days=max_age_days)]
    return d.sort_values("review_date", ascending=False, kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------------------- data health
STALE_AFTER = timedelta(hours=48)
HEALTH_COLUMNS = ["property", "property_name", "stored", "last_ok_at", "latest_status", "latest_error", "stale",
                  "truncated", "reported_total", "coverage_note"]


def _utc(ts) -> pd.Timestamp:
    """A stored timestamp as UTC; text that is not a time (a damaged row) becomes NaT instead of an exception."""
    try:
        t = pd.Timestamp(ts)
        if pd.isna(t):
            return pd.NaT
        return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")
    except (ValueError, TypeError, OverflowError):
        return pd.NaT


def _flag(value) -> bool:
    """A stored 0/1 flag; anything else that is not clearly 'true' counts as no."""
    return str(value).strip().lower() in ("1", "true", "yes")


def _count_or_none(value) -> int | None:
    try:
        n = int(float(value))
    except (ValueError, TypeError, OverflowError):
        return None
    return n if n >= 0 else None


def data_health(db_path, now: datetime | None = None) -> pd.DataFrame:
    """One row per property (configured ones always, plus any other slug seen in the data).

    ``last_ok_at`` is when the last successful scrape finished (NaT if never); ``stale`` is True when
    that is more than 48 hours before ``now`` (default: current UTC time) or there has never been one.
    """
    now_ts = _utc(now) if now is not None else pd.Timestamp.now(tz="UTC")
    stored = _read(db_path, "SELECT property, COUNT(*) AS stored FROM reviews GROUP BY property",
                   ["property", "stored"])
    ok = _read(db_path, "SELECT property, MAX(COALESCE(finished_at, started_at)) AS last_ok_at "
                        "FROM scrape_runs WHERE status = 'ok' GROUP BY property", ["property", "last_ok_at"])
    latest = _read(db_path, "SELECT property, status AS latest_status, error AS latest_error FROM scrape_runs "
                            "WHERE id IN (SELECT MAX(id) FROM scrape_runs GROUP BY property)",
                   ["property", "latest_status", "latest_error"])
    # Did the last successful run stop at the page cap? (Missing columns on old databases read as "no".)
    # Older databases lack the newer ledger columns (added together). Two literal queries, never built from text.
    have_cols = set(_read(db_path, "SELECT * FROM scrape_runs LIMIT 0", []).columns)
    if {"stop_reason", "since_days"} <= have_cols:
        cover = _read(db_path, "SELECT property, truncated, reported_total, stop_reason, since_days FROM scrape_runs "
                               "WHERE id IN (SELECT MAX(id) FROM scrape_runs WHERE status = 'ok' GROUP BY property)",
                      ["property", "truncated", "reported_total", "stop_reason", "since_days"])
    else:
        cover = _read(db_path, "SELECT property, truncated, reported_total FROM scrape_runs "
                               "WHERE id IN (SELECT MAX(id) FROM scrape_runs WHERE status = 'ok' GROUP BY property)",
                      ["property", "truncated", "reported_total"])
    cover_by = {r.property: (_flag(r.truncated), _count_or_none(r.reported_total),
                             getattr(r, "stop_reason", None), _count_or_none(getattr(r, "since_days", None)))
                for r in cover.itertuples()}
    slugs = list(BY_SLUG)
    for frame in (stored, ok, latest):
        slugs += [s for s in frame["property"] if s not in slugs]
    stored_by = dict(zip(stored["property"], stored["stored"]))
    ok_by = dict(zip(ok["property"], ok["last_ok_at"]))
    latest_by = {r.property: (r.latest_status, r.latest_error) for r in latest.itertuples()}
    rows = []
    for slug in slugs:
        last_ok = _utc(ok_by[slug]) if ok_by.get(slug) else pd.NaT
        status, error = latest_by.get(slug, (None, None))
        truncated, reported, stop_reason, since_days = cover_by.get(slug, (False, None, None, None))
        have = int(stored_by.get(slug, 0))
        note = ""
        if truncated and stop_reason == "date_window" and since_days:
            note = (f"Showing reviews from the last {since_days} days only. Older reviews are not collected "
                    f"(date window), so history before that is missing.")
        elif truncated:
            of = f" of {int(reported):,}" if reported is not None else ""
            note = (f"Showing the newest {have:,}{of} reviews on Booking.com. Older reviews are not collected "
                    f"(page limit), so history before the oldest one shown is missing.")
        rows.append({
            "property": slug, "property_name": _name(slug), "stored": int(stored_by.get(slug, 0)),
            "last_ok_at": last_ok, "latest_status": status, "latest_error": error,
            "stale": bool(pd.isna(last_ok) or now_ts - last_ok > STALE_AFTER),
            "truncated": truncated,
            "reported_total": reported,
            "coverage_note": note,
        })
    return pd.DataFrame(rows, columns=HEALTH_COLUMNS)


# ---------------------------------------------------------------------------- insights
MAX_INSIGHTS = 6
_SCORE_MOVE = 0.3            # portfolio average must move this much to be called out as good/bad
_PROPERTY_MOVE = 0.5         # same for a single property (noisier, so a higher bar)
_SPIKE_MIN_COUNT = 3         # a property+topic spike needs this many negative mentions this week...
_SPIKE_MIN_RISE = 2          # ...and at least this many more than last week


@dataclass(frozen=True)
class Insight:
    text: str
    kind: str                       # "alert" | "good" | "info"
    property: str | None = None     # property slug when the insight is about one property
    n: int = 0                      # number of reviews the statement rests on


def _count(n: int, noun: str = "review") -> str:
    return f"{n} {noun}" if n == 1 else f"{n} {noun}s"


def _day(d: date) -> str:
    return f"{d:%a} {d.day} {d:%b}"


def _pct(count: int, n: int) -> int:
    return int(100 * count / n + 0.5)


def _score_insight(cmp: WeekComparison):
    cur, prev, d = cmp.current, cmp.previous, cmp.delta
    text = f"Average rating this week was {cur.avg_rating:.1f} from {_count(cur.n)}"
    kind = "info"
    if d is None:
        text += ". There were no reviews last week to compare with."
    else:
        both_ok = cur.n >= LOW_SAMPLE_BELOW and prev.n >= LOW_SAMPLE_BELOW
        if round(d, 2) <= -_SCORE_MOVE:
            text += f", down {abs(d):.1f} from {prev.avg_rating:.1f} last week ({_count(prev.n)})."
            kind = "alert" if both_ok else "info"
        elif round(d, 2) >= _SCORE_MOVE:
            text += f", up {d:.1f} from {prev.avg_rating:.1f} last week ({_count(prev.n)})."
            kind = "good" if both_ok else "info"
        else:
            text += f", level with last week ({prev.avg_rating:.1f} from {_count(prev.n)})."
        if prev.n < LOW_SAMPLE_BELOW:
            text += f" Last week had only {_count(prev.n)}, so treat the comparison with caution."
    return Insight(text, kind, None, cur.n)


def _topic_insight(df, topics, ws, cur: WeekSummary, prev: WeekSummary):
    end, pend = ws + timedelta(days=6), ws - timedelta(days=1)
    if cur.negative == 0:
        return Insight(f"No negative reviews this week (0 of {_count(cur.n)} rated below {NEGATIVE_BELOW:g}).",
                       "good", None, cur.n)
    cc = comment_counts(df, ws, end)
    if cc.n_with_comment == 0:
        verb = "has" if cur.negative == 1 else "have"
        return Insight(f"{_count(cur.negative, 'negative review')} this week {verb} no written comment, "
                       "so their topics cannot be identified.", "info", None, cur.negative)
    shares = topic_shares(df, topics, ws, end)
    if len(shares) == 0:
        return None
    top = shares.iloc[0]
    n, c = cc.n_with_comment, int(top["count"])
    label = str(top["label"]).lower()
    pct = _pct(c, n)
    text = f"{pct}% of negative reviews with a written comment this week mentioned {label} ({c} of {n}"
    if cc.n_without_comment:
        k = cc.n_without_comment
        text += f"; {k} other negative {'review' if k == 1 else 'reviews'} had no comment"
    text += ")"
    pcc = comment_counts(df, ws - timedelta(days=7), pend)
    pn = pcc.n_with_comment
    alert = n >= LOW_SAMPLE_BELOW
    if pn == 0:
        text += ". There were no negative reviews with a written comment last week to compare with."
    else:
        prev_shares = topic_shares(df, topics, ws - timedelta(days=7), pend).set_index("topic")["count"]
        pc = int(prev_shares.get(top["topic"], 0))
        ppct = _pct(pc, pn)
        direction = "up from" if pct > ppct else "down from" if pct < ppct else "the same as"
        text += f", {direction} {ppct}% last week ({pc} of {pn})."
        alert = alert and pct > ppct
    if n < LOW_SAMPLE_BELOW:
        text += (f" Only {_count(n, 'negative review')} with a written comment this week, "
                 "so treat with caution.")
    elif 0 < pn < LOW_SAMPLE_BELOW:
        text += f" Last week had only {_count(pn, 'negative review')} with a written comment, so treat the comparison with caution."
    return Insight(text, "alert" if alert else "info", None, n)


def _property_insight(df, ws):
    bd = property_breakdown(df, ws)
    bd = bd[(bd["n"] > 0) & (bd["prev_n"] > 0) & (bd["delta"].abs() >= _PROPERTY_MOVE)]
    if len(bd) == 0:
        return None
    r = bd.assign(_a=bd["delta"].abs()).sort_values(["_a", "n", "property_name"],
                                                    ascending=[False, False, True]).iloc[0]
    up = r["delta"] > 0
    text = (f"{r['property_name']} {'rose' if up else 'dropped'} {abs(r['delta']):.1f} points to "
            f"{r['avg_rating']:.1f} this week ({_count(int(r['n']))}), from {r['prev_avg']:.1f} last week "
            f"({_count(int(r['prev_n']))}).")
    small = r["n"] < LOW_SAMPLE_BELOW or r["prev_n"] < LOW_SAMPLE_BELOW
    if small:
        text += " Small sample, treat with caution."
    kind = "info" if small else ("good" if up else "alert")
    return Insight(text, kind, r["property"], int(r["n"]))


def _spike_insights(df, topics, ws):
    end = ws + timedelta(days=6)
    cur = topic_by_property(df, topics, ws, end)
    prev = topic_by_property(df, topics, ws - timedelta(days=7), end - timedelta(days=7))
    if len(cur) == 0:
        return []
    m = cur.merge(prev[["property", "topic", "count"]], on=["property", "topic"], how="left",
                  suffixes=("", "_prev")).fillna({"count_prev": 0})
    m["rise"] = m["count"] - m["count_prev"]
    m = m[(m["count"] >= _SPIKE_MIN_COUNT) & (m["rise"] >= _SPIKE_MIN_RISE)]
    m = m.sort_values(["rise", "count", "property_name", "topic"], ascending=[False, False, True, True])
    out = []
    for r in m.head(2).itertuples():
        out.append(Insight(
            f"{r.property_name}: {_count(int(r.count), 'negative review')} mentioned {str(r.label).lower()} "
            f"this week, up from {int(r.count_prev)} last week.", "alert", r.property, int(r.count)))
    return out


def _unreplied_insight(df, ws):
    end = pd.Timestamp(ws + timedelta(days=6))
    u = unreplied_reviews(df, band="negative")
    u = u[u["review_date"] <= end]
    if len(u) == 0:
        return None
    total, this_week = len(u), int((u["review_date"] >= pd.Timestamp(ws)).sum())
    verb = "has" if total == 1 else "have"
    text = f"{_count(total, 'negative review')} {verb} no hotel reply yet ({this_week} of them from this week)."
    by_prop = u.groupby("property_name").size().sort_values(ascending=False)
    if len(by_prop) > 1 and by_prop.iloc[0] > by_prop.iloc[1]:
        text += f" {by_prop.index[0]} has the most ({int(by_prop.iloc[0])})."
    return Insight(text, "alert", None, total)


def generate_insights(df, topics, week_start) -> list[Insight]:
    """Plain-English findings for one week, most important first, at most six.

    Every percentage carries its count; small samples are flagged rather than over-claimed.
    ``topics`` may be None or empty (then topic findings are simply left out).
    """
    ws = week_start_of(week_start)
    d = _prepare(df)
    cmp = compare_weeks(d, ws)
    cur = cmp.current
    if cur.n == 0:
        return [Insight(f"No reviews were published in the week starting {_day(ws)}, "
                        "so there is nothing to report.", "info", None, 0)]
    several = d["property"].nunique() >= 2
    # (is_notice, base importance, insight); sorted below by notice, then alert > good > info, then base.
    found: list[tuple[bool, int, Insight]] = []
    if cur.n < LOW_SAMPLE_BELOW:
        found.append((True, 0, Insight(
            f"Only {_count(cur.n)} this week, which is not enough to be sure about any trend. "
            "Treat these numbers with caution.", "info", None, cur.n)))
    found.append((False, 1, _score_insight(cmp)))
    topic = _topic_insight(d, topics, ws, cur, cmp.previous)
    if topic:
        found.append((False, 2, topic))
    unreplied = _unreplied_insight(d, ws)
    if unreplied:
        found.append((False, 3, unreplied))
    if several:
        prop = _property_insight(d, ws)
        if prop:
            found.append((False, 4, prop))
        if topics is not None and len(topics):
            found += [(False, 5, s) for s in _spike_insights(d, topics, ws)]
    rank = {"alert": 0, "good": 1, "info": 2}
    found.sort(key=lambda f: (not f[0], rank[f[2].kind], f[1]))
    return [f[2] for f in found][:MAX_INSIGHTS]
