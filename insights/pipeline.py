"""Write review_topics for every stored review. Idempotent; safe to run after every scrape.

    python -m insights.pipeline --db data/reviews.db
"""
import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass

from insights.classify import CLASSIFIER_REVISION, MAX_TEXT_CHARS, classify_review
from insights.topics import TAXONOMY_VERSION

SCHEMA = """
CREATE TABLE IF NOT EXISTS review_topics (
    review_key       TEXT NOT NULL,
    topic            TEXT NOT NULL,     -- one of the ids above
    polarity         TEXT NOT NULL CHECK (polarity IN ('positive','negative')),
    evidence         TEXT NOT NULL,     -- the exact sentence that triggered the tag
    method           TEXT NOT NULL,     -- 'keywords' (later maybe 'llm')
    taxonomy_version TEXT NOT NULL,
    PRIMARY KEY (review_key, topic, polarity)
);
-- Remembers which reviews were processed, so reviews with zero tags are not re-run every time.
CREATE TABLE IF NOT EXISTS review_topics_state (
    review_key       TEXT PRIMARY KEY,
    content_hash     TEXT NOT NULL,
    taxonomy_version TEXT NOT NULL
);
"""


@dataclass(frozen=True)
class ClassifyResult:
    reviews_seen: int
    reviews_classified: int
    reviews_skipped: int
    tags_written: int


def classify_all(db_path: str) -> ClassifyResult:
    """(Re)classify reviews that are new, changed since tagging, or tagged under an older taxonomy."""
    if db_path != ":memory:" and not os.path.exists(db_path):
        raise FileNotFoundError(f"Database not found: {db_path}")
    version = TAXONOMY_VERSION
    state_version = f"{version}+{CLASSIFIER_REVISION}"   # what the 'done' memory compares; review_topics keeps `version`
    db = sqlite3.connect(db_path, timeout=30)
    try:
        db.executescript(SCHEMA)
        done = {k: (h, v) for k, h, v in db.execute(
            "SELECT review_key, content_hash, taxonomy_version FROM review_topics_state")}
        seen = classified = skipped = written = 0
        # substr(): the classifier reads at most MAX_TEXT_CHARS, so a 5 MB review is never pulled into memory whole.
        rows = db.execute("SELECT review_key, substr(liked, 1, ?), substr(disliked, 1, ?), content_hash FROM reviews",
                          (MAX_TEXT_CHARS * 2, MAX_TEXT_CHARS * 2)).fetchall()
        for key, liked, disliked, content_hash in rows:
            seen += 1
            if done.get(key) == (content_hash, state_version):
                skipped += 1
                continue
            tags = classify_review(liked, disliked)
            db.execute("DELETE FROM review_topics WHERE review_key=?", (key,))
            db.executemany(
                "INSERT INTO review_topics (review_key, topic, polarity, evidence, method, taxonomy_version)"
                " VALUES (?,?,?,?,?,?)",
                [(key, t.topic, t.polarity, t.evidence, t.method, version) for t in tags],
            )
            db.execute(
                "INSERT INTO review_topics_state (review_key, content_hash, taxonomy_version) VALUES (?,?,?)"
                " ON CONFLICT(review_key) DO UPDATE SET content_hash=excluded.content_hash,"
                " taxonomy_version=excluded.taxonomy_version",
                (key, content_hash, state_version),
            )
            classified += 1
            written += len(tags)
        db.commit()
        return ClassifyResult(seen, classified, skipped, written)
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Classify review topics into the review_topics table.")
    parser.add_argument("--db", default="data/reviews.db")
    args = parser.parse_args(argv)
    try:
        r = classify_all(args.db)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except sqlite3.Error as exc:     # a directory, a damaged file, something that is not SQLite, or a locked database
        print(f"Could not classify {args.db}: not a usable SQLite review database ({type(exc).__name__}).",
              file=sys.stderr)
        return 1
    print(f"{r.reviews_seen} reviews seen, {r.reviews_classified} classified, "
          f"{r.reviews_skipped} skipped, {r.tags_written} tags written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
