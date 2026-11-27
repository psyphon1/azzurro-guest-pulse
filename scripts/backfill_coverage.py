"""Record, after the fact, that a past successful scrape did not collect every review.

    python scripts/backfill_coverage.py --db data/reviews.db --property venus-potts-point-sydney \\
        --reported-total 2386 --stop-reason ended_early --evidence "console output of the full run: ..."

Older scraper versions did not write coverage into the run ledger, so the dashboard wrongly shows such a run as
complete. This annotates ONLY the latest successful run of one property (truncated, reported_total, stop_reason) and
writes where the facts came from into that run's ``error`` column. It never touches the reviews table, and refuses
to overwrite coverage the scraper already recorded.
"""
import argparse
import os
import sqlite3
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scraper.models import clean_text  # noqa: E402
from scraper.store import MAX_ERROR_LEN, ReviewStore, StoreError  # noqa: E402

STOP_REASONS = ("page_cap", "ended_early")
MAX_EVIDENCE = 300
MAX_REPORTED_TOTAL = 10_000_000
_PREFIX = "Coverage backfilled from "


@dataclass(frozen=True)
class BackfillResult:
    run_id: int
    property: str
    reported_total: int
    stop_reason: str


def backfill(db_path: str, property_slug: str, reported_total: int, stop_reason: str, evidence: str) -> BackfillResult:
    if stop_reason not in STOP_REASONS:
        raise ValueError(f"stop_reason must be one of {', '.join(STOP_REASONS)}, got {stop_reason!r}")
    if isinstance(reported_total, bool) or not isinstance(reported_total, int) or not 0 < reported_total < MAX_REPORTED_TOTAL:
        raise ValueError(f"reported_total must be a whole number between 1 and {MAX_REPORTED_TOTAL - 1:,}")
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("evidence is required: say where these numbers came from")
    evidence = clean_text(evidence, MAX_EVIDENCE + 1)
    if len(evidence) > MAX_EVIDENCE:
        raise ValueError(f"evidence is too long ({len(evidence)} characters, at most {MAX_EVIDENCE})")
    if not evidence:
        raise ValueError("evidence is required: say where these numbers came from")

    store = ReviewStore(db_path)          # opening it migrates the ledger columns into an old database
    store.close()
    con = sqlite3.connect(db_path, timeout=30)
    try:
        run = con.execute("SELECT id, stop_reason, error FROM scrape_runs WHERE property=? AND status='ok' "
                          "ORDER BY id DESC LIMIT 1", (property_slug,)).fetchone()
        if run is None:
            raise ValueError(f"{property_slug!r} has no successful run to annotate")
        run_id, existing_reason, existing_error = run
        if existing_reason:
            raise ValueError(f"run {run_id} already has a stop reason ({existing_reason!r}); refusing to overwrite it")
        note = _PREFIX + evidence
        if existing_error:
            note = f"{existing_error} | {note}"
        note = clean_text(note, MAX_ERROR_LEN)
        cur = con.execute("UPDATE scrape_runs SET truncated=1, reported_total=?, stop_reason=?, error=? "
                          "WHERE id=? AND stop_reason IS NULL", (reported_total, stop_reason, note, run_id))
        if cur.rowcount != 1:
            raise ValueError(f"run {run_id} was changed by someone else; nothing was written")
        con.commit()
    finally:
        con.close()
    return BackfillResult(run_id, property_slug, reported_total, stop_reason)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--db", required=True)
    ap.add_argument("--property", required=True)
    ap.add_argument("--reported-total", required=True, type=int)
    ap.add_argument("--stop-reason", required=True, choices=STOP_REASONS)
    ap.add_argument("--evidence", required=True, help="where the numbers came from (max 300 characters)")
    args = ap.parse_args(argv)
    try:
        r = backfill(args.db, args.property, args.reported_total, args.stop_reason, args.evidence)
    except (ValueError, StoreError) as exc:
        print(f"Not changed: {exc}", file=sys.stderr)
        return 1
    print(f"Run {r.run_id} of {r.property} marked partial: reported_total={r.reported_total}, stop_reason={r.stop_reason}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
