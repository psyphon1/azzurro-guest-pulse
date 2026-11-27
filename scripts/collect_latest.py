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
import random
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOCK = ROOT / "data" / ".collect.lock"
STATUS = ROOT / "data" / ".collect.status.json"
PAUSE_S = 8             # seconds between hotels (doubled at most); a latest-only fetch reads about one page each
MAX_PAGES = 20           # safety cap for hotels we already have (10 reviews per page)
FIRST_FETCH_PAGES = 1    # a hotel with no stored reviews: only the newest page


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
        from scraper.config import PROPERTIES

        import sqlite3

        def keys() -> dict[str, str]:
            try:
                con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
                try:
                    return dict(con.execute("SELECT review_key, property FROM reviews").fetchall())
                finally:
                    con.close()
            except sqlite3.Error:
                return {}

        before = keys()
        _write_status(state="collecting", started_at=started)
        print(f"[{time.strftime('%H:%M:%S')}] collecting new reviews (incremental, all hotels)", flush=True)
        code = 0
        stopped = False
        try:
            for i, prop in enumerate(PROPERTIES):
                if i:   # same courtesy pause as scraper.run between hotels
                    wait = random.uniform(PAUSE_S, PAUSE_S * 2)
                    print(f"Waiting {wait:.0f}s before the next hotel ...", flush=True)
                    time.sleep(wait)
                # One fresh process per hotel: each browser starts clean, whatever happened to the previous one.
                # Only the latest reviews: a hotel we already have stops at the first review it already stored (and never
                # reads more than MAX_PAGES); a hotel with nothing stored yet gets just the newest page, not a year back.
                stored = sum(1 for p in before.values() if p == prop.slug)
                pages = MAX_PAGES if stored else FIRST_FETCH_PAGES
                rc = subprocess.run([sys.executable, "-m", "scraper.run", "--property", prop.slug, "--mode", "incremental",
                                     "--max-pages", str(pages), "--hidden-window", "--db", args.db],
                                    cwd=str(ROOT)).returncode
                code = code or rc
        except KeyboardInterrupt:      # Stop button: skip the remaining hotels, but keep and show what arrived
            stopped = True
            print(f"[{time.strftime('%H:%M:%S')}] stopped by the user; saving what was already fetched", flush=True)
        _write_status(state="tagging", started_at=started, collect_exit=code)
        print(f"[{time.strftime('%H:%M:%S')}] tagging topics", flush=True)
        tag_main(["--db", args.db])
        after = keys()
        new = [k for k in after if k not in before]
        per_hotel: dict[str, int] = {}
        for k in new:
            per_hotel[after[k]] = per_hotel.get(after[k], 0) + 1
        _write_status(state="stopped" if stopped else "done", started_at=started, collect_exit=code,
                      finished_at=datetime.now(timezone.utc).isoformat(),
                      new_count=len(new), new_keys=new[:2000], new_by_hotel=per_hotel)
        print(f"[{time.strftime('%H:%M:%S')}] done: {len(new)} new reviews {per_hotel} "
              f"(collector exit code {code})", flush=True)
        return 0
    except KeyboardInterrupt:  # the dashboard's Stop button sends an interrupt; pages already saved are kept
        _write_status(state="stopped", started_at=started, finished_at=datetime.now(timezone.utc).isoformat())
        print(f"[{time.strftime('%H:%M:%S')}] stopped by the user", flush=True)
        return 130
    except Exception as exc:  # recorded for the dashboard, then re-raised into the log
        _write_status(state="failed", started_at=started, error=f"{type(exc).__name__}: {exc}"[:300])
        raise
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
