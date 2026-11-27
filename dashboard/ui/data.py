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


def today_sydney() -> date:
    """Today's date on the Sydney clock. Everything on the page that depends on "today" calls this (as
    `D.today_sydney()`, looked up at call time) so a test can replace it to freeze the date."""
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
    today = today or today_sydney()
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
    return f"{short_day(start)} to {short_day(end)} {end.year}"


def short_day(d: date) -> str:
    """'Mon 9 Nov' (no zero padding, which strftime cannot do portably)."""
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


@dataclass(frozen=True)
class WeekLabels:
    """The words for one focus week. Only the real current Sydney week may be called "this week"; any other
    week is named by its dates, so the cards can never claim to be live when they describe a finished week."""
    current: bool
    heading: str        # "Week of 16 Nov at a glance" / "This week so far at a glance"
    score: str          # card title for the average score
    previous: str       # card title for the week before
    count: str          # card title for the number of reviews
    in_week: str        # "in the week of Mon 16 Nov" / "this week so far", for sentences
    prior: str          # the week before, as a label: "last week" / "previous week"
    prior_in: str       # the week before, in a sentence: "last week" / "in the previous week"


def week_labels(focus: date, today: date) -> WeekLabels:
    mon = short_day(focus)
    if focus == monday_of(today):
        return WeekLabels(True, "This week so far at a glance", "Guest score, this week so far",
                          f"Previous week ({short_day(focus - timedelta(days=7))})", "Reviews, this week so far",
                          "this week so far", "last week", "last week")
    return WeekLabels(False, f"Week of {focus.day} {focus.strftime('%b')} at a glance", f"Guest score, week of {mon}",
                      f"Previous week ({short_day(focus - timedelta(days=7))})", f"Reviews, week of {mon}",
                      f"in the week of {mon}", "previous week", "in the previous week")


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


# --- top filter bar (polish pass) ----------------------------------------------------------------------------------
PERIODS = ["This week", "Last week", "Last 30 days", "All time", "Custom"]
DEFAULT_PERIOD = "This week"
SMALL_SAMPLE = 10            # below this many reviews a number gets a "Small sample" badge


def period_range(period: str, today: date, first: date, last: date,
                 custom: tuple[date, date] | None = None) -> tuple[date, date, date]:
    """(start, end, focus Monday) for a filter-bar period. The focus week is what "Worth a look" describes."""
    this_monday = monday_of(today)
    if period == "Last week":
        w = this_monday - timedelta(days=7)
        return w, w + timedelta(days=6), w
    if period == "Last 30 days":
        return today - timedelta(days=29), today, this_monday
    if period == "All time":
        return min(first, today), max(last, today), monday_of(min(last, today))
    if period == "Custom" and custom:
        s, e = sorted(custom)
        return s, e, monday_of(min(e, today, max(last, s)))
    return this_monday, today, this_monday                   # This week (so far): the default


def previous_range(start: date, end: date) -> tuple[date, date]:
    """The window of the same length just before [start, end], for "vs previous" deltas."""
    days = (end - start).days + 1
    return start - timedelta(days=days), start - timedelta(days=1)


def period_label(period: str, start: date, end: date, today: date) -> str:
    if period == "This week":
        return f"This week so far, {short_day(start)} to today"
    if period == "Last week":
        return f"Last week, {nice_range(start, end)}"
    if period == "Last 30 days":
        return f"Last 30 days, {short_day(start)} to today"
    return nice_range(start, end)


def parse_query(params: dict, valid_slugs: list[str]) -> tuple[str, list[str] | None, tuple[date, date] | None]:
    """Filters from the URL (untrusted): unknown values are ignored, never trusted."""
    def first(key):
        v = params.get(key)
        if isinstance(v, (list, tuple)):
            v = v[0] if v else None
        return str(v)[:200] if v is not None else None

    period = first("period")
    period = period if period in PERIODS else DEFAULT_PERIOD
    raw = first("hotels")
    slugs = None
    if raw:
        picked = [s for s in raw.split(",") if s in valid_slugs]
        slugs = list(dict.fromkeys(picked)) or None
    custom = None
    try:
        f, t = first("from"), first("to")
        if f and t:
            custom = (date.fromisoformat(f), date.fromisoformat(t))
    except ValueError:
        custom = None
    return period, slugs, custom


def to_query(period: str, slugs: list[str], all_slugs: list[str], custom: tuple[date, date] | None) -> dict[str, str]:
    out = {"period": period}
    if slugs and set(slugs) != set(all_slugs):
        out["hotels"] = ",".join(slugs)
    if period == "Custom" and custom:
        out["from"], out["to"] = custom[0].isoformat(), custom[1].isoformat()
    return out


# --- KPI row -------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Kpi:
    label: str
    value: str
    delta: float | None          # signed change vs the previous window, in the KPI's own unit
    delta_text: str              # "Up 0.4 vs previous", "No comparison"
    tone: str                    # "good" | "bad" | "flat"
    caption: str
    small: bool                  # small-sample badge


def _window(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    return df[(df["review_date"] >= pd.Timestamp(start)) & (df["review_date"] <= pd.Timestamp(end))]


def _delta(cur, prev, unit: str, up_is_good: bool, digits: int = 1) -> tuple[float | None, str, str]:
    if cur is None or prev is None:
        return None, "No comparison", "flat"
    d = round(cur - prev, digits)
    if abs(d) < 10 ** -digits / 2:
        return 0.0, "No change vs previous", "flat"
    word = "Up" if d > 0 else "Down"
    amount = f"{abs(d):.{digits}f}" if digits else f"{abs(int(d))}"
    tone = "good" if (d > 0) == up_is_good else "bad"
    return d, f"{word} {amount}{unit} vs previous", tone


def kpis(df: pd.DataFrame, start: date, end: date, today: date) -> list[Kpi]:
    """The four numbers at the top: average score, review count, % negative, unanswered negatives (90 days)."""
    ps, pe = previous_range(start, end)
    cur, prev = _window(df, start, end), _window(df, ps, pe)
    n, pn = len(cur), len(prev)
    avg = round(float(cur["rating"].mean()), 1) if n else None
    pavg = round(float(prev["rating"].mean()), 1) if pn else None
    neg = round(100 * int((cur["band"] == "negative").sum()) / n) if n else None
    pneg = round(100 * int((prev["band"] == "negative").sum()) / pn) if pn else None
    d1, t1, c1 = _delta(avg, pavg, "", up_is_good=True)
    d2, t2, c2 = _delta(n, pn, "", up_is_good=True, digits=0) if pn or n else (None, "No comparison", "flat")
    d3, t3, c3 = _delta(neg, pneg, " pts", up_is_good=False, digits=0)
    since = today - timedelta(days=90)
    unanswered = df[(df["band"] == "negative") & (~df["has_reply"]) & (df["review_date"] >= pd.Timestamp(since))]
    neg_n = int((cur["band"] == "negative").sum())
    return [
        Kpi("Average score", "–" if avg is None else f"{avg:.1f}", d1, t1, c1,
            f"out of 10, from {n} review{'s' if n != 1 else ''}", 0 < n < SMALL_SAMPLE),
        Kpi("Reviews", f"{n}", d2, t2, c2, f"previous period: {pn}", 0 < n < SMALL_SAMPLE),
        Kpi("Negative", "–" if neg is None else f"{neg}%", d3, t3, c3,
            f"{neg_n} of {n} scored under 5", 0 < n < SMALL_SAMPLE),
        Kpi("Unanswered negatives", f"{len(unanswered)}", None, "Last 90 days", "flat",
            "negative reviews with no hotel reply", False),
    ]


# --- hotel cards ---------------------------------------------------------------------------------------------------
_SPARK = "▁▂▃▄▅▆▇█"


def sparkline(values: list[float | None]) -> str:
    """Weekly averages as block characters on the 1 to 10 scale ("·" for a week with no reviews)."""
    out = []
    for v in values:
        if v is None or pd.isna(v):
            out.append("·")
        else:
            out.append(_SPARK[min(len(_SPARK) - 1, max(0, int((float(v) - 1) / 9 * len(_SPARK))))])
    return "".join(out)


@dataclass(frozen=True)
class HotelRow:
    slug: str
    name: str
    n: int
    avg: float | None
    delta: float | None
    prev_n: int
    top_complaint: str | None
    spark: str
    spark_label: str


def hotel_rows(df: pd.DataFrame, topics: pd.DataFrame, slugs: list[str], names: dict[str, str],
               start: date, end: date, labels: dict[str, str]) -> list[HotelRow]:
    ps, pe = previous_range(start, end)
    weeks = [monday_of(end) - timedelta(weeks=i) for i in range(7, -1, -1)]
    neg_tags = topics[topics["polarity"] == "negative"] if topics is not None and len(topics) else None
    out = []
    for slug in slugs:
        h = df[df["property"] == slug]
        cur, prev = _window(h, start, end), _window(h, ps, pe)
        avg = round(float(cur["rating"].mean()), 1) if len(cur) else None
        pavg = round(float(prev["rating"].mean()), 1) if len(prev) else None
        top = None
        if neg_tags is not None and len(cur):
            c = neg_tags[neg_tags["review_key"].isin(cur["review_key"])].groupby("topic")["review_key"].nunique()
            if len(c):
                tid = c.sort_values(ascending=False).index[0]
                top = f"{labels.get(tid, tid)} ({int(c[tid])})"
        vals = []
        for w in weeks:
            wk = _window(h, w, w + timedelta(days=6))
            vals.append(round(float(wk["rating"].mean()), 1) if len(wk) else None)
        spoken = ", ".join("none" if v is None else f"{v:.1f}" for v in vals)
        out.append(HotelRow(slug, names.get(slug, slug), len(cur), avg,
                            None if avg is None or pavg is None else round(avg - pavg, 1), len(prev), top,
                            sparkline(vals), f"Weekly average score, last 8 weeks: {spoken}"))
    return out


# --- feed presets from "Worth a look" ------------------------------------------------------------------------------
QUICK_FILTERS = ["Negative", "Needs reply", "Has comment", "Safety"]
_PRESET_TO_PILL = {"neg": "Negative", "noreply": "Needs reply", "text": "Has comment", "safety": "Safety"}


def apply_preset(preset, valid_topics: set[str], valid_slugs: set[str]) -> tuple[list[str], str, str | None]:
    """A "Worth a look" action -> (quick filter pills, topic choice, hotel slug). Unknown values are dropped."""
    if not isinstance(preset, dict):
        return [], "", None
    pills = [pill for key, pill in _PRESET_TO_PILL.items() if preset.get(key) is True]
    topic = preset.get("topic") if isinstance(preset.get("topic"), str) else ""
    parsed = parse_topic_choice(topic, {t: t for t in valid_topics})
    slug = preset.get("property") if preset.get("property") in valid_slugs else None
    return pills, (topic if parsed else ""), slug


def safety_keys(chips: dict) -> set[str]:
    return {k for k, tags in chips.items() if any(t == "safety" and p == "negative" for t, p, _ in tags)}


# --- KPI charts: what costs points, reply backlog, guest segments, safety by month -------------------------------
def topic_impact(df: pd.DataFrame, topics: pd.DataFrame, labels: dict[str, str]) -> pd.DataFrame:
    """Per complaint topic: average score of reviews that complain about it vs every other review in `df`.
    Sorted by the biggest cost first (most negative delta)."""
    cols = ["topic", "label", "n", "avg_with", "avg_without", "delta"]
    if df is None or df.empty or topics is None or len(topics) == 0:
        return pd.DataFrame(columns=cols)
    neg = topics[(topics["polarity"] == "negative") & topics["review_key"].isin(df["review_key"])]
    rows = []
    for tid, keys in neg.groupby("topic")["review_key"]:
        hit = df["review_key"].isin(set(keys))
        if not hit.any() or hit.all():
            continue
        w, wo = float(df.loc[hit, "rating"].mean()), float(df.loc[~hit, "rating"].mean())
        rows.append({"topic": tid, "label": labels.get(tid, tid), "n": int(hit.sum()), "avg_with": round(w, 1),
                     "avg_without": round(wo, 1), "delta": round(w - wo, 1)})
    out = pd.DataFrame(rows, columns=cols)
    return out.sort_values(["delta", "n"], ascending=[True, False], kind="stable").reset_index(drop=True)


def reply_weekly(df: pd.DataFrame, end: date, weeks: int = 12) -> pd.DataFrame:
    """Negative reviews per Monday-Sunday week (the last `weeks` weeks up to `end`) and how many got a reply."""
    first = monday_of(end) - timedelta(weeks=weeks - 1)
    out = []
    for i in range(weeks):
        w = first + timedelta(weeks=i)
        neg = _window(df, w, w + timedelta(days=6))
        neg = neg[neg["band"] == "negative"]
        n, r = len(neg), int(neg["has_reply"].sum())
        out.append({"week_start": pd.Timestamp(w), "negatives": n, "replied": r, "unreplied": n - r,
                    "rate": round(100 * r / n) if n else None})
    return pd.DataFrame(out)


def reply_by_hotel(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    neg = _window(df, start, end)
    neg = neg[neg["band"] == "negative"]
    g = neg.groupby("property_name").agg(negatives=("review_key", "size"), replied=("has_reply", "sum")).reset_index()
    g["replied"] = g["replied"].astype(int)
    g["rate"] = (100 * g["replied"] / g["negatives"]).round().astype(int)
    return g.sort_values("rate", kind="stable").reset_index(drop=True)


def segment_scores(df: pd.DataFrame, column: str, min_n: int = SMALL_SAMPLE, top: int = 8) -> pd.DataFrame:
    """Average score and % negative per value of `column` (traveller type, room type), least happy first.
    Groups with fewer than `min_n` reviews are left out (one guest would decide them)."""
    cols = ["segment", "n", "avg", "pct_negative"]
    if df is None or df.empty or column not in df.columns:
        return pd.DataFrame(columns=cols)
    seg = df[column].fillna("").astype(str).str.strip()
    d = df.assign(_seg=seg)[seg != ""]
    g = d.groupby("_seg").agg(n=("rating", "size"), avg=("rating", "mean"),
                              neg=("band", lambda b: int((b == "negative").sum()))).reset_index()
    g = g[g["n"] >= min_n]
    if g.empty:
        return pd.DataFrame(columns=cols)
    g = g.sort_values("n", ascending=False).head(top)
    out = pd.DataFrame({"segment": g["_seg"], "n": g["n"].astype(int), "avg": g["avg"].round(1),
                        "pct_negative": (100 * g["neg"] / g["n"]).round().astype(int)})
    return out.sort_values(["avg", "n"], ascending=[True, False], kind="stable").reset_index(drop=True)


def safety_monthly(df: pd.DataFrame, topics: pd.DataFrame, end: date, months: int = 12) -> pd.DataFrame:
    """Reviews with a safety complaint per calendar month and hotel, for the `months` months up to `end`."""
    cols = ["month", "property_name", "count"]
    if df is None or df.empty or topics is None or len(topics) == 0:
        return pd.DataFrame(columns=cols)
    keys = set(topics.loc[(topics["topic"] == "safety") & (topics["polarity"] == "negative"), "review_key"])
    first = (pd.Timestamp(end).to_period("M") - (months - 1)).to_timestamp()
    hit = df[df["review_key"].isin(keys) & (df["review_date"] >= first) & (df["review_date"] <= pd.Timestamp(end))]
    if hit.empty:
        return pd.DataFrame(columns=cols)
    g = hit.assign(month=hit["review_date"].dt.to_period("M").dt.to_timestamp()) \
        .groupby(["month", "property_name"]).size().reset_index(name="count")
    return g[cols]
