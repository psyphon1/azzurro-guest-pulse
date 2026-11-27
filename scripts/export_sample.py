"""Export the sample data deliverables from the live database.

    python scripts/export_sample.py --per-property 300

Writes
  data/sample_reviews.csv        newest N reviews per hotel, readable in Excel (reviewer identity never included,
                                 e-mails and phone numbers masked, cells safe against spreadsheet formulas)
  data/sample/reviews_sample.db  the same reviews with their topic tags and run history, so the dashboard can be
                                 demonstrated without scraping:  REVIEWS_DB=data/sample/reviews_sample.db streamlit run dashboard/app.py

The live database is opened read-only. Everything CSV-related reuses the dashboard's hardened export code.
"""
import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dashboard.ui import data as D  # noqa: E402
from insights import metrics  # noqa: E402
from scraper.config import PROPERTIES  # noqa: E402
from scraper.store import ReviewStore  # noqa: E402


@dataclass
class ExportResult:
    csv_path: str
    sample_db_path: str | None
    per_property: dict[str, int] = field(default_factory=dict)

    @property
    def missing_hotels(self) -> list[str]:
        return [slug for slug, n in self.per_property.items() if n == 0]


def _newest(df, per_property: int):
    parts = []
    for p in PROPERTIES:
        sub = df[df["property"] == p.slug].sort_values(["review_date", "review_key"], ascending=[False, True])
        parts.append(sub.head(per_property))
    import pandas as pd
    return pd.concat(parts, ignore_index=True) if parts else df.iloc[0:0]


MAX_PER_PROPERTY = 10_000


def _same_file(a: str, b: str) -> bool:
    return Path(a).resolve() == Path(b).resolve()


def _is_previous_sample(path: str) -> bool:
    """Only a file that really is one of our review databases may be replaced; anything else is somebody's data."""
    try:
        con = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        try:
            return con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='reviews'").fetchone() is not None
        finally:
            con.close()
    except sqlite3.Error:
        return False


def export_sample(db_path: str, csv_path: str, per_property: int = 300,
                  sample_db_path: str | None = "data/sample/reviews_sample.db") -> ExportResult:
    if not isinstance(per_property, int) or not 1 <= per_property <= MAX_PER_PROPERTY:
        raise ValueError(f"per_property must be between 1 and {MAX_PER_PROPERTY}")
    if _same_file(csv_path, db_path):
        raise ValueError("the CSV path is the live database: refusing to overwrite it")
    if sample_db_path:
        if _same_file(sample_db_path, db_path):
            raise ValueError("the sample database must not be the live database")
        if _same_file(sample_db_path, csv_path):
            raise ValueError("the CSV and the sample database cannot be the same file")
        if os.path.exists(sample_db_path) and not _is_previous_sample(sample_db_path):
            raise ValueError(f"{sample_db_path} exists and is not a previous sample database; refusing to delete it")

    reviews = metrics.load_reviews(db_path)
    topics = metrics.load_topics(db_path)
    chosen = _newest(reviews, per_property)
    keys = list(chosen["review_key"])

    chips = D.topic_chips(topics[topics["review_key"].isin(keys)]) if len(topics) else {}
    payload, _ = D.feed_to_csv_limited(chosen, chips, D.topic_labels())
    Path(csv_path).parent.mkdir(parents=True, exist_ok=True)
    Path(csv_path).write_bytes(payload)

    counts = {p.slug: int((chosen["property"] == p.slug).sum()) for p in PROPERTIES}
    if sample_db_path:
        _write_sample_db(db_path, sample_db_path, keys)
    return ExportResult(csv_path=csv_path, sample_db_path=sample_db_path, per_property=counts)


def _write_sample_db(src_path: str, dest_path: str, keys: list[str]) -> None:
    Path(dest_path).parent.mkdir(parents=True, exist_ok=True)
    if os.path.exists(dest_path):
        os.remove(dest_path)
    ReviewStore(dest_path).close()                        # creates the current schema
    con = sqlite3.connect(dest_path)
    try:
        con.execute("ATTACH DATABASE ? AS src", (Path(src_path).resolve().as_uri() + "?mode=ro",))
    except sqlite3.OperationalError:
        con.close()
        raise
    try:
        con.execute("CREATE TEMP TABLE keep (review_key TEXT PRIMARY KEY)")
        con.executemany("INSERT OR IGNORE INTO keep VALUES (?)", [(k,) for k in keys])
        con.execute("INSERT INTO main.reviews SELECT * FROM src.reviews WHERE review_key IN (SELECT review_key FROM keep)")
        con.execute("DELETE FROM main.scrape_runs")
        run_cols = [r[1] for r in con.execute("PRAGMA main.table_info(scrape_runs)")]
        have = {r[1] for r in con.execute("PRAGMA src.table_info(scrape_runs)")}
        shared = ", ".join(c for c in run_cols if c in have)   # column names come from our own schema
        con.execute(f"INSERT INTO main.scrape_runs ({shared}) SELECT {shared} FROM src.scrape_runs WHERE id IN "
                    "(SELECT MAX(id) FROM src.scrape_runs WHERE status = 'ok' GROUP BY property)")
        for table in ("review_topics", "review_topics_state"):
            exists = con.execute("SELECT 1 FROM src.sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
            if exists:
                con.execute(f"CREATE TABLE IF NOT EXISTS main.{table} AS SELECT * FROM src.{table} WHERE 0")
                con.execute(f"INSERT INTO main.{table} SELECT * FROM src.{table} WHERE review_key IN (SELECT review_key FROM keep)")
        con.commit()
    finally:
        con.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/reviews.db")
    ap.add_argument("--csv", default="data/sample_reviews.csv")
    ap.add_argument("--sample-db", default="data/sample/reviews_sample.db")
    ap.add_argument("--per-property", type=int, default=300, help=f"1 to {MAX_PER_PROPERTY}")
    args = ap.parse_args()
    try:
        out = export_sample(args.db, args.csv, args.per_property, args.sample_db)
    except ValueError as exc:
        ap.error(str(exc))
    for slug, n in out.per_property.items():
        print(f"{slug}: {n} reviews exported" + ("  <-- NO DATA" if n == 0 else ""))
    print(f"Wrote {out.csv_path} and {out.sample_db_path}")


if __name__ == "__main__":
    main()
