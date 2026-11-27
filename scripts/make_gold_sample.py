"""Draw a random, reproducible sample of REAL reviews for independent hand-labelling.

    python scripts/make_gold_sample.py --db data/reviews.db --n 100 --seed 7 --out data/raw/gold_sample.json

Only English reviews that have written text are sampled (the keyword classifier is English only; rating-only reviews
cannot carry a topic). The sample is spread evenly across hotels. E-mail addresses and phone numbers are masked, and
records hold no reviewer identity and NO classifier output, so whoever labels them is blind to what the classifier said.
The database is opened read-only.
"""
import argparse
import json
import os
import random
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dashboard.ui.privacy import mask_pii  # noqa: E402


def _is_english(row) -> bool:
    return (row["language"] or "").lower().startswith("en")


def sample_reviews(db_path: str, n: int, seed: int) -> list[dict]:
    con = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT review_key, property, liked, disliked, language FROM reviews "
            "WHERE (COALESCE(liked, '') <> '' OR COALESCE(disliked, '') <> '') ORDER BY review_key"
        ).fetchall()
    finally:
        con.close()
    by_property: dict[str, list] = {}
    for row in rows:
        if _is_english(row):
            by_property.setdefault(row["property"], []).append(row)

    rng = random.Random(seed)
    slugs = sorted(by_property)
    if not slugs:
        return []
    picked: list = []
    # even split; hotels with fewer reviews than their share give the remainder to the others
    quota = {s: n // len(slugs) for s in slugs}
    for s in slugs[: n - sum(quota.values())]:
        quota[s] += 1
    leftovers = 0
    for s in slugs:
        pool = by_property[s]
        take = min(quota[s], len(pool))
        leftovers += quota[s] - take
        picked += rng.sample(pool, take)
    if leftovers:
        chosen = {r["review_key"] for r in picked}
        rest = [r for s in slugs for r in by_property[s] if r["review_key"] not in chosen]
        picked += rng.sample(rest, min(leftovers, len(rest)))
    rng.shuffle(picked)
    return [{"id": r["review_key"], "property": r["property"],
             "liked": mask_pii(r["liked"] or ""), "disliked": mask_pii(r["disliked"] or "")} for r in picked]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/reviews.db")
    ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default="data/raw/gold_sample.json")
    args = ap.parse_args()
    if not args.out.lower().endswith(".json"):
        ap.error("--out must be a .json file (refusing to write over anything else)")
    sample = sample_reviews(args.db, args.n, args.seed)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(sample, indent=1, ensure_ascii=False))
    print(f"Wrote {len(sample)} reviews to {args.out}")


if __name__ == "__main__":
    main()
