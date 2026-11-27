import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Iterable

from scraper.models import RejectedReview, Review

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
    truncated INTEGER DEFAULT 0, reported_total INTEGER, max_pages INTEGER
);

CREATE TABLE IF NOT EXISTS quarantine (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    property TEXT NOT NULL, review_key TEXT, reason TEXT NOT NULL, seen_at TEXT NOT NULL
);
"""


@dataclass
class UpsertResult:
    new: int = 0
    updated: int = 0
    unchanged: int = 0


def _content_hash(review: Review) -> str:
    # Everything that can legitimately change after publication (text edits, hotel replies, votes).
    data = review.model_dump(mode="json", exclude={"property"})
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


class ReviewStore:
    def __init__(self, path: str, clock: Callable[[], datetime] | None = None):
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Upgrade databases created by an older version (CREATE IF NOT EXISTS never adds columns)."""
        have = {r["name"] for r in self._db.execute("PRAGMA table_info(scrape_runs)")}
        for column, ddl in (("truncated", "INTEGER DEFAULT 0"), ("reported_total", "INTEGER"), ("max_pages", "INTEGER")):
            if column not in have:
                self._db.execute(f"ALTER TABLE scrape_runs ADD COLUMN {column} {ddl}")
        self._db.commit()

    def _now(self) -> str:
        return self._clock().isoformat()

    # --- reviews -------------------------------------------------------
    def upsert_reviews(self, reviews: Iterable[Review]) -> UpsertResult:
        result = UpsertResult()
        now = self._now()
        for review in reviews:
            digest = _content_hash(review)
            existing = self._db.execute(
                "SELECT content_hash FROM reviews WHERE review_key = ?", (review.review_key,)
            ).fetchone()
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

    def count(self, property_slug: str) -> int:
        return self._db.execute(
            "SELECT COUNT(*) FROM reviews WHERE property=?", (property_slug,)
        ).fetchone()[0]

    def get(self, review_key: str) -> sqlite3.Row | None:
        return self._db.execute("SELECT * FROM reviews WHERE review_key=?", (review_key,)).fetchone()

    def known_keys(self, property_slug: str) -> set[str]:
        rows = self._db.execute("SELECT review_key FROM reviews WHERE property=?", (property_slug,))
        return {r[0] for r in rows}

    # --- quarantine ----------------------------------------------------
    def quarantine(self, property_slug: str, rejected: Iterable[RejectedReview]) -> None:
        now = self._now()
        self._db.executemany(
            "INSERT INTO quarantine (property, review_key, reason, seen_at) VALUES (?,?,?,?)",
            [(property_slug, r.review_key, r.reason, now) for r in rejected],
        )
        self._db.commit()

    def quarantined(self, property_slug: str) -> list[sqlite3.Row]:
        return self._db.execute("SELECT * FROM quarantine WHERE property=?", (property_slug,)).fetchall()

    # --- run ledger ----------------------------------------------------
    def start_run(self, property_slug: str, mode: str) -> int:
        cur = self._db.execute(
            "INSERT INTO scrape_runs (property, mode, started_at, status) VALUES (?,?,?, 'running')",
            (property_slug, mode, self._now()),
        )
        self._db.commit()
        return cur.lastrowid

    def finish_run(self, run_id: int, status: str, pages: int, new: int, updated: int,
                   rejected: int, error: str | None, truncated: bool = False,
                   reported_total: int | None = None, max_pages: int | None = None) -> None:
        self._db.execute(
            "UPDATE scrape_runs SET finished_at=?, status=?, pages=?, new=?, updated=?, rejected=?, error=?, "
            "truncated=?, reported_total=?, max_pages=? WHERE id=?",
            (self._now(), status, pages, new, updated, rejected, error,
             int(truncated), reported_total, max_pages, run_id),
        )
        self._db.commit()

    def last_successful_run(self, property_slug: str) -> sqlite3.Row | None:
        return self._db.execute(
            "SELECT * FROM scrape_runs WHERE property=? AND status='ok' ORDER BY id DESC LIMIT 1",
            (property_slug,),
        ).fetchone()

    def latest_run(self, property_slug: str) -> sqlite3.Row | None:
        return self._db.execute(
            "SELECT * FROM scrape_runs WHERE property=? ORDER BY id DESC LIMIT 1", (property_slug,)
        ).fetchone()

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
