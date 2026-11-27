"""Fetch the newest reviews for every hotel, add them to the database and re-tag topics.

Started by the dashboard's "Fetch latest reviews" button (or by hand):

    python scripts/collect_latest.py --db data/reviews.db

Runs the collector in incremental mode (it stops at the first page with no new reviews, so a normal run is short),
then the topic pipeline. A lock file stops two runs at once; the log goes to data/collect.log.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOCK = ROOT / "data" / ".collect.lock"
STATUS = ROOT / "data" / ".collect.status.json"


def _write_status(**fields) -> None:
    STATUS.write_text(json.dumps({**fields, "updated_at": datetime.now(timezone.utc).isoformat()}))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=str(ROOT / "data" / "reviews.db"))
    args = ap.parse_args(argv)
    started = datetime.now(timezone.utc).isoformat()
    LOCK.write_text(json.dumps({"pid": os.getpid(), "started_at": started}))
    try:
        from insights.pipeline import main as tag_main
        from scraper.run import main as collect_main

        _write_status(state="collecting", started_at=started)
        print(f"[{time.strftime('%H:%M:%S')}] collecting new reviews (incremental, all hotels)", flush=True)
        code = collect_main(["--property", "all", "--mode", "incremental", "--db", args.db])
        _write_status(state="tagging", started_at=started, collect_exit=code)
        print(f"[{time.strftime('%H:%M:%S')}] tagging topics", flush=True)
        tag_main(["--db", args.db])
        _write_status(state="done", started_at=started, collect_exit=code,
                      finished_at=datetime.now(timezone.utc).isoformat())
        print(f"[{time.strftime('%H:%M:%S')}] done (collector exit code {code})", flush=True)
        return 0
    except Exception as exc:  # recorded for the dashboard, then re-raised into the log
        _write_status(state="failed", started_at=started, error=f"{type(exc).__name__}: {exc}"[:300])
        raise
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
