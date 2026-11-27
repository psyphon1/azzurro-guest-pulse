"""Databases for the browser tests. All synthetic and built in a temp folder; the real databases are never opened."""
import random
import shutil
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from insights.pipeline import classify_all
from scraper.config import PROPERTIES
from scraper.models import Review
from scraper.store import ReviewStore
from scripts.make_demo_db import make
from tests.test_dashboard_nodata import BLOCK_ERR, EMPTY, NEWEST, build_blocked_db

__all__ = ["main_db", "evil_db", "empty_db", "big_db", "corrupt_db", "renamed_copy", "XSS_PAYLOADS", "EMPTY", "NEWEST"]


def main_db(folder: Path) -> Path:
    """The realistic situation: 3 hotels with data (two partial), Central Sydney blocked with no reviews, topics tagged."""
    path = build_blocked_db(folder / "azzurro_reviews.db")
    classify_all(str(path))
    return path


XSS_PAYLOADS = {
    "script": "<script>window.__xss_script = 1</script>",
    "img": '<img src=x onerror="window.__xss_img = 1">',
    "svg": '"><svg onload="window.__xss_svg = 1">',
    "iframe": '<iframe src="https://attacker.example/frame"></iframe>',
    "style": "<style>body{display:none !important}</style>",
    "link": '<a href="javascript:window.__xss_link=1">click</a>',
    "md_link": "[x](javascript:window.__xss_md=1)",
    "pixel": "![](https://attacker.example/pixel.png?viewer)",
    "email": "write to jo.smith@example.com",
    "phone": "call 0412 345 678",
    "formula": '=HYPERLINK("http://attacker.example","click")',
}


def evil_db(folder: Path) -> Path:
    """Every free-text field carries a hostile payload, inside this week so it is on screen."""
    path = folder / "evil_reviews.db"
    store = ReviewStore(str(path), clock=lambda: datetime(2026, 11, 27, 8, 0, tzinfo=timezone.utc))
    payloads = list(XSS_PAYLOADS.values())
    reviews = []
    for i, p in enumerate(payloads):
        for prop in PROPERTIES[:2]:
            reviews.append(Review(
                review_key=f"evil-{prop.slug}-{i}", property=prop.slug, rating=2.0 + (i % 5),
                review_date=NEWEST - timedelta(days=i % 6), language="en",
                title=p, liked=p, disliked=f"The room was dirty and noisy. {p}", host_reply=p,
                room_type=p[:60], traveller_type="Couple", reviewer_country="Australia"))
    store.upsert_reviews(reviews)
    for prop in PROPERTIES:
        run = store.start_run(prop.slug, "full")
        store.finish_run(run, "failed" if prop.slug == EMPTY else "ok", 1, len(reviews) // 2, 0, 0,
                         "<script>window.__xss_error=1</script> boom" if prop.slug == EMPTY else None)
    store.close()
    classify_all(str(path))
    return path


def empty_db(folder: Path) -> Path:
    path = folder / "empty.db"
    ReviewStore(str(path)).close()
    return path


def big_db(folder: Path, n_per_hotel: int = 1500) -> Path:
    """About 6,000 reviews over a year: for load-time and interaction-speed checks."""
    path = folder / "big_reviews.db"
    rng = random.Random(5)
    store = ReviewStore(str(path), clock=lambda: datetime(2026, 11, 27, 8, 0, tzinfo=timezone.utc))
    for prop in PROPERTIES:
        reviews = [make(rng, prop.slug, NEWEST - timedelta(days=rng.randint(0, 364)), i) for i in range(n_per_hotel)]
        store.upsert_reviews(reviews)
        run = store.start_run(prop.slug, "full")
        store.finish_run(run, "ok", 150, n_per_hotel, 0, 0, None)
    store.close()
    classify_all(str(path))
    return path


def corrupt_db(folder: Path) -> Path:
    path = folder / "corrupt.db"
    path.write_bytes(b"this is not a sqlite database " * 40)
    return path


def renamed_copy(src: Path, new_name: str) -> Path:
    dest = src.parent / new_name
    shutil.copy(src, dest)
    return dest
