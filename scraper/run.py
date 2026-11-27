"""Command line entry point.

  python -m scraper.run --property all --mode incremental
  python -m scraper.run --property olympic-paddington --mode full
"""
import argparse
import sys

from scraper.browser import fetch_pages
from scraper.collector import collect_property
from scraper.config import BY_SLUG, DB_PATH, DEFAULT_MAX_PAGES, PROPERTIES
from scraper.store import ReviewStore


def _positive_int(text: str) -> int:
    try:
        value = int(text)
    except ValueError:
        value = 0
    if value < 1:
        raise argparse.ArgumentTypeError(f"{text!r} is not a positive whole number")
    return value


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Collect public Booking.com reviews")
    ap.add_argument("--property", default="all", help="property slug or 'all'")
    ap.add_argument("--mode", choices=["incremental", "full"], default="incremental")
    ap.add_argument("--db", default=DB_PATH)
    ap.add_argument("--max-pages", type=_positive_int, default=DEFAULT_MAX_PAGES,
                    help=f"newest-first page limit per hotel, 10 reviews per page (default {DEFAULT_MAX_PAGES})")
    args = ap.parse_args(argv)

    if args.property != "all" and args.property not in BY_SLUG:
        ap.error(f"unknown property {args.property!r}; choose from: {', '.join(BY_SLUG)} or all")
    targets = PROPERTIES if args.property == "all" else [BY_SLUG[args.property]]

    store = ReviewStore(args.db)
    failures = 0
    for prop in targets:
        print(f"[{prop.name}] {args.mode} run ...", flush=True)
        s = collect_property(prop.slug, fetch_pages(prop.url, prop.slug), store, args.mode, max_pages=args.max_pages)
        print(f"[{prop.name}] {s.status}: pages={s.pages} new={s.new} updated={s.updated} "
              f"rejected={s.rejected} stored={s.stored_total} reported_total={s.reported_total}"
              + (" DRIFT" if s.drift else "") + (f" error={s.error}" if s.error else ""), flush=True)
        if s.truncated:
            print(f"[{prop.name}] TRUNCATED: {s.coverage_note}", flush=True)
        failures += s.status != "ok" or s.drift
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
