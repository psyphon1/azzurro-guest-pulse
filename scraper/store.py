import functools
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from scraper.errors import StoreError
from scraper.models import MAX_KEY_LEN, RejectedReview, Review, clean_text

SCHEMA = """
CREATE TABLE IF NOT EXISTS reviews (
    review_key TEXT PRIMARY KEY,
    property TEXT NOT NULL,
    rating REAL NOT NULL,
    review_date TEXT NOT NULL,
    title TEXT, liked TEXT, disliked TEXT, language TEXT,
    reviewer_country TEXT, traveller_type TEXT, room_type TEXT,
    nights INTEGER, checkin_date TEXT, checkout_date TEXT,
    host_reply TEXT, helpful_votes INTEGER DEFAULT 0,
    content_hash TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    missing_since TEXT
);
CREATE INDEX IF NOT EXISTS idx_reviews_property_date ON reviews(property, review_date);

CREATE TABLE IF NOT EXISTS scrape_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property TEXT NOT NULL, mode TEXT NOT NULL,
    started_at TEXT NOT NULL, finished_at TEXT,
    status TEXT NOT NULL,
    pages INTEGER DEFAULT 0, new INTEGER DEFAULT 0, updated INTEGER DEFAULT 0,
    rejected INTEGER DEFAULT 0, error TEXT,
    truncated INTEGER DEFAULT 0, reported_total INTEGER, max_pages INTEGER,
    stop_reason TEXT, since_days INTEGER
);

CREATE TABLE IF NOT EXISTS quarantine (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property TEXT NOT NULL, review_key TEXT, reason TEXT NOT NULL, seen_at TEXT NOT NULL
);
"""


MAX_QUARANTINE_PER_CALL = 50      # rows one page may add (the true count still goes in scrape_runs.rejected)
MAX_QUARANTINE_ROWS = 10_000      # rolling ceiling per property: oldest evidence is dropped first
BUSY_TIMEOUT_S = 30               # wait this long for another process (e.g. a running scrape) before giving up
MAX_REASON_LEN = 300
MAX_ERROR_LEN = 500
RUN_STATUSES = {"running", "ok", "blocked", "failed", "interrupted"}


@dataclass
class UpsertResult:
    new: int = 0
    updated: int = 0
    unchanged: int = 0
    conflicts: int = 0   # reviews refused because their key already belongs to another property


def _explain(exc: sqlite3.Error, path: str) -> StoreError:
    text = str(exc).lower()
    if "locked" in text or "busy" in text:
        why = (f"The database {path!r} is locked by another process (is a scrape or another job still running?). "
               "Nothing was changed; wait for it to finish and run again.")
    elif "not a database" in text or "encrypted" in text:
        why = f"{path!r} is not a SQLite database. It was left untouched; choose another --db path."
    elif "malformed" in text or "corrupt" in text:
        why = f"The database {path!r} looks damaged ({exc}). Restore it from a backup."
    elif "unable to open" in text or "readonly" in text or "read-only" in text:
        why = f"Cannot open or write the database {path!r} ({exc}). Check the path and permissions."
    else:
        why = f"Database error on {path!r}: {exc}"
    return StoreError(why)


def _guarded(method):
    """Turn raw sqlite3 failures into StoreError and roll back, so a failed call never leaves half a batch."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        try:
            return method(self, *args, **kwargs)
        except sqlite3.Error as exc:
            self._rollback()
            raise _explain(exc, self._path) from exc
        except Exception:
            self._rollback()
            raise
    return wrapper


def _content_hash(review: Review) -> str:
    # Everything that can legitimately change after publication (text edits, hotel replies, votes).
    data = review.model_dump(mode="json", exclude={"property"})
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class ReviewStore:
    def __init__(self, path: str, clock: Callable[[], datetime] | None = None,
                 busy_timeout_s: float | None = None):
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._path = path
        try:
            self._db = sqlite3.connect(path, timeout=BUSY_TIMEOUT_S if busy_timeout_s is None else busy_timeout_s)
            self._db.row_factory = sqlite3.Row
            self._db.executescript(SCHEMA)
            self._migrate()
        except sqlite3.Error as exc:
            raise _explain(exc, path) from exc

    def _rollback(self) -> None:
        try:
            self._db.rollback()
        except sqlite3.Error:
            pass

    def _migrate(self) -> None:
        """Upgrade databases created by an older version (CREATE IF NOT EXISTS never adds columns)."""
        have = {r["name"] for r in self._db.execute("PRAGMA table_info(scrape_runs)")}
        for column, ddl in (("truncated", "INTEGER DEFAULT 0"), ("reported_total", "INTEGER"), ("max_pages", "INTEGER"),
                            ("stop_reason", "TEXT"), ("since_days", "INTEGER")):
            if column not in have:
                self._db.execute(f"ALTER TABLE scrape_runs ADD COLUMN {column} {ddl}")
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def _now(self) -> str:
        return self._clock().isoformat()

    # --- reviews -------------------------------------------------------
    @_guarded
    def upsert_reviews(self, reviews: Iterable[Review]) -> UpsertResult:
        result = UpsertResult()
        now = self._now()
        for review in reviews:
            digest = _content_hash(review)
            existing = self._db.execute(
                "SELECT content_hash, property FROM reviews WHERE review_key = ?", (review.review_key,)
            ).fetchone()
            if existing is not None and existing["property"] != review.property:
                # review_key is the only primary key. A response for property B that reuses a key held by property A
                # must not move, overwrite or even touch A's row. Refuse it and leave a trace.
                self._add_quarantine(review.property, [RejectedReview(
                    review_key=review.review_key, reason="review_key already belongs to another property")], now)
                result.conflicts += 1
                continue
            values = review.model_dump(mode="json")
            if existing is None:
                cols = list(values) + ["content_hash", "first_seen", "last_seen"]
                params = list(values.values()) + [digest, now, now]
                self._db.execute(
                    f"INSERT INTO reviews ({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", params
                )
                result.new += 1
            elif existing["content_hash"] != digest:
                sets = ",".join(f"{c}=?" for c in values) + ",content_hash=?,last_seen=?,missing_since=NULL"
                self._db.execute(
                    f"UPDATE reviews SET {sets} WHERE review_key=?",
                    list(values.values()) + [digest, now, review.review_key],
                )
                result.updated += 1
            else:
                self._db.execute(
                    "UPDATE reviews SET last_seen=?, missing_since=NULL WHERE review_key=?",
                    (now, review.review_key),
                )
                result.unchanged += 1
        self._db.commit()
        return result

    @_guarded
    def count(self, property_slug: str) -> int:
        return self._db.execute(
            "SELECT COUNT(*) FROM reviews WHERE property=?", (property_slug,)
        ).fetchone()[0]

    @_guarded
    def get(self, review_key: str) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM reviews WHERE review_key=?", (review_key,)).fetchone()

    @_guarded
    def known_keys(self, property_slug: str) -> set[str]:
        rows = self._db.execute("SELECT review_key FROM reviews WHERE property=?", (property_slug,))
        return {r[0] for r in rows}

    # --- quarantine ----------------------------------------------------
    @_guarded
    def quarantine(self, property_slug: str, rejected: Iterable[RejectedReview]) -> None:
        self._add_quarantine(property_slug, rejected, self._now())
        self._db.commit()

    def _add_quarantine(self, property_slug: str, rejected: Iterable[RejectedReview], now: str) -> None:
        rows = []
        for r in rejected:
            if len(rows) >= MAX_QUARANTINE_PER_CALL:
                break
            key = clean_text(r.review_key, MAX_KEY_LEN) if isinstance(r.review_key, str) else None
            rows.append((property_slug, key, clean_text(r.reason, MAX_REASON_LEN), now))
        self._db.executemany(
            "INSERT INTO quarantine (property, review_key, reason, seen_at) VALUES (?,?,?,?)", rows)
        self._db.execute(
            "DELETE FROM quarantine WHERE property=? AND id NOT IN "
            "(SELECT id FROM quarantine WHERE property=? ORDER BY id DESC LIMIT ?)",
            (property_slug, property_slug, MAX_QUARANTINE_ROWS),
        )

    @_guarded
    def quarantined(self, property_slug: str) -> list[sqlite3.Row]:
        return self._db.execute("SELECT * FROM quarantine WHERE property=?", (property_slug,)).fetchall()

    # --- run ledger ----------------------------------------------------
    @_guarded
    def start_run(self, property_slug: str, mode: str) -> int:
        cur = self._db.execute(
            "INSERT INTO scrape_runs (property, mode, started_at, status) VALUES (?,?,?, 'running')",
            (property_slug, mode, self._now()),
        )
        self._db.commit()
        return cur.lastrowid

    @_guarded
    def finish_run(self, run_id: int, status: str, pages: int, new: int, updated: int,
                   rejected: int, error: str | None, truncated: bool = False,
                   reported_total: int | None = None, max_pages: int | None = None,
                   stop_reason: str | None = None, since_days: int | None = None) -> None:
        if status not in RUN_STATUSES:
            raise ValueError(f"unknown run status {status!r}")
        if error is not None:
            error = clean_text(error, MAX_ERROR_LEN)   # remote-influenced text: no escapes, no newlines, bounded
        self._db.execute(
            "UPDATE scrape_runs SET finished_at=?, status=?, pages=?, new=?, updated=?, rejected=?, error=?, "
            "truncated=?, reported_total=?, max_pages=?, stop_reason=?, since_days=? WHERE id=?",
            (self._now(), status, pages, new, updated, rejected, error,
             int(truncated), reported_total, max_pages, stop_reason, since_days, run_id),
        )
        self._db.commit()

    @_guarded
    def last_successful_run(self, property_slug: str) -> sqlite3.Row | None:
        return self._db.execute(
            "SELECT * FROM scrape_runs WHERE property=? AND status='ok' ORDER BY id DESC LIMIT 1",
            (property_slug,),
        ).fetchone()

    @_guarded
    def latest_run(self, property_slug: str) -> sqlite3.Row | None:
        return self._db.execute(
            "SELECT * FROM scrape_runs WHERE property=? ORDER BY id DESC LIMIT 1", (property_slug,)
        ).fetchone()

    @_guarded
    def mark_missing(self, property_slug: str, seen_keys: set[str]) -> int:
        """After a complete run: flag reviews we hold that Booking no longer shows. Never deletes."""
        now = self._now()
        known = self._db.execute(
            "SELECT review_key FROM reviews WHERE property=? AND missing_since IS NULL", (property_slug,)
        ).fetchall()
        gone = [k[0] for k in known if k[0] not in seen_keys]
        self._db.executemany("UPDATE reviews SET missing_since=? WHERE review_key=?", [(now, k) for k in gone])
        self._db.commit()
        return len(gone)

    @_guarded
    def close_stale_runs(self, property_slug: str) -> int:
        """A run still marked 'running' when a new one starts means the process was killed.
        Close it so the data-health panel never claims a run is in progress forever."""
        cur = self._db.execute(
            "UPDATE scrape_runs SET status='interrupted', finished_at=?, "
            "error='Run did not finish (process stopped before completing)' "
            "WHERE property=? AND status='running'",
            (self._now(), property_slug),
        )
        self._db.commit()
        return cur.rowcount
