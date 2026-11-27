"""Command line entry point.

  python -m scraper.run --property all --mode incremental
  python -m scraper.run --property olympic-paddington --mode full
"""
import argparse
import os
import random
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from scraper.browser import fetch_pages
from scraper.collector import collect_property
from scraper.config import BY_SLUG, DB_PATH, DEFAULT_MAX_PAGES, DEFAULT_SINCE_DAYS, HARD_MAX_PAGES, PROPERTIES
from scraper.errors import StoreError
from scraper.models import clean_text
from scraper.store import ReviewStore

MAX_PAGES_LIMIT = HARD_MAX_PAGES
MAX_SINCE_DAYS = 3650
DEFAULT_PAUSE_S = 60        # polite gap between hotels (random between PAUSE and 2 x PAUSE)
BLOCK_BACKOFF_S = 180       # after a block, wait this long (plus up to 50%) and try that hotel once more
BLOCK_RETRIES = 1

# Wrapped so tests can run without waiting or depending on today's date.
_sleep = time.sleep


def _today():
    return datetime.now(ZoneInfo("Australia/Sydney")).date()


def _show(text: object, limit: int = 200) -> str:
    """Anything that came from outside (argv, the remote server) is cleaned before it reaches the terminal."""
    return clean_text(str(text), limit)


def _bounded_int(text: str, name: str, low: int, high: int) -> int:
    try:
        value = int(text)
    except ValueError:
        value = low - 1
    if value < low:
        word = "a positive whole number" if low == 1 else "a whole number of at least 0"
        raise argparse.ArgumentTypeError(f"{_show(text, 40)!r} is not {word}")
    if value > high:
        raise argparse.ArgumentTypeError(f"{name} must be at most {high} (got {_show(text, 40)})")
    return value


def _positive_int(text: str) -> int:
    return _bounded_int(text, "--max-pages", 1, MAX_PAGES_LIMIT)


def _since_days(text: str) -> int:
    return _bounded_int(text, "--since-days", 1, MAX_SINCE_DAYS)


def _pause(text: str) -> int:
    return _bounded_int(text, "--pause", 0, 3600)


def _db_path(text: str) -> str:
    """Refuse values SQLite would treat specially: '' and ':memory:' are throw-away databases (data silently lost),
    'file:' is a URI, a NUL byte is truncation, a directory or a missing folder is a typo."""
    if not text.strip() or "\x00" in text:
        raise argparse.ArgumentTypeError("--db must be a real file path")
    if text.strip() == ":memory:" or text.lower().startswith("file:"):
        raise argparse.ArgumentTypeError("--db must be a file path, not an in-memory or URI database")
    if os.path.isdir(text):
        raise argparse.ArgumentTypeError(f"--db {_show(text, 80)!r} is a directory, expected a file")
    parent = os.path.dirname(os.path.abspath(text))
    if not os.path.isdir(parent):
        raise argparse.ArgumentTypeError(f"the folder for --db does not exist: {_show(parent, 80)!r}")
    return text


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Collect public Booking.com reviews")
    ap.add_argument("--property", default="all", help="property slug or 'all'")
    ap.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    ap.add_argument("--db", type=_db_path, default=DB_PATH)
    ap.add_argument("--max-pages", type=_positive_int, default=DEFAULT_MAX_PAGES,
                    help=f"newest-first page limit per hotel, 10 reviews per page "
                         f"(default {DEFAULT_MAX_PAGES}, at most {MAX_PAGES_LIMIT})")
    ap.add_argument("--since-days", type=_since_days, default=DEFAULT_SINCE_DAYS,
                    help=f"only collect reviews from the last N days: stop at the first page that is entirely older "
                         f"(default {DEFAULT_SINCE_DAYS})")
    ap.add_argument("--no-date-window", action="store_true", help="read all the way back (still limited by --max-pages)")
    ap.add_argument("--pause", type=_pause, default=DEFAULT_PAUSE_S,
                    help=f"seconds to rest between hotels, randomised up to double (default {DEFAULT_PAUSE_S}; 0 = none)")
    args = ap.parse_args(argv)

    if args.property != "all" and args.property not in BY_SLUG:
        ap.error(f"unknown property {_show(args.property, 60)!r}; choose from: {', '.join(BY_SLUG)} or all")
    targets = PROPERTIES if args.property == "all" else [BY_SLUG[args.property]]

    try:
        return _run(args, targets)
    except StoreError as exc:
        print(f"Database problem: {_show(exc, 400)}", file=sys.stderr, flush=True)
        return 2


def _collect_once(prop, store, args):
    since = None if args.no_date_window else args.since_days
    s = collect_property(prop.slug, fetch_pages(prop.url, prop.slug), store, args.mode,
                         max_pages=args.max_pages, since_days=since, today=_today())
    print(f"[{prop.name}] {s.status}: pages={s.pages} new={s.new} updated={s.updated} "
          f"rejected={s.rejected} stored={s.stored_total} reported_total={s.reported_total}"
          + (f" stop={s.stop_reason}" if s.stop_reason else "")
          + (" DRIFT" if s.drift else "") + (f" error={_show(s.error, 500)}" if s.error else ""), flush=True)
    if s.truncated:
        print(f"[{prop.name}] TRUNCATED: {s.coverage_note}", flush=True)
    return s


def _run(args, targets) -> int:
    store = ReviewStore(args.db)
    failures = 0
    for i, prop in enumerate(targets):
        if i and args.pause:
            wait = random.uniform(args.pause, args.pause * 2)
            print(f"Resting {wait:.0f}s before the next hotel (keeps the load on Booking.com low) ...", flush=True)
            _sleep(wait)
        print(f"[{prop.name}] {args.mode} run ...", flush=True)
        s = _collect_once(prop, store, args)
        for _ in range(BLOCK_RETRIES):
            if s.status != "blocked":
                break
            wait = random.uniform(BLOCK_BACKOFF_S, BLOCK_BACKOFF_S * 1.5)
            print(f"[{prop.name}] blocked: waiting {wait:.0f}s and retrying once ...", flush=True)
            _sleep(wait)
            s = _collect_once(prop, store, args)
        if s.status == "blocked":
            print(f"[{prop.name}] still blocked: try again later (a few hours is usually enough). "
                  "Pages already saved were kept.", flush=True)
        failures += s.status != "ok" or s.drift
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
