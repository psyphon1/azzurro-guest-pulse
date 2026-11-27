"""Build a SYNTHETIC demo database for developing and testing the dashboard.

Everything here is invented. It exists so the UI and metrics can be built before (or without)
live scraping. The file name contains "demo" so the dashboard shows a warning banner.

  python scripts/make_demo_db.py            # writes data/demo.db
"""
import hashlib
import os
import random
import sys
from datetime import date, datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scraper.config import PROPERTIES  # noqa: E402
from scraper.models import Review  # noqa: E402
from scraper.store import ReviewStore  # noqa: E402

OUT = "data/demo.db"
TODAY = date(2026, 11, 27)  # fixed so the output is deterministic
WEEKS = 12

GOOD = {
    "location": ["Great location, close to everything.", "Perfect spot for the stadium.", "Easy walk to the train."],
    "staff": ["The reception staff were friendly and helpful.", "Lovely, helpful team."],
    "value": ["Good value for money.", "Cheap and cheerful, great price."],
    "check_in": ["Check-in was quick and easy.", "Self check-in worked smoothly."],
    "room_condition": ["The room was comfortable and the bed was great."],
    "cleanliness": ["The room was spotless and clean."],
    "facilities": ["The kitchen was well equipped.", "Fast wifi."],
    "noise": ["It was quiet at night."],
}
BAD = {
    "cleanliness": ["The bathroom was dirty and the floor needed a mop.", "Found cockroaches in the room.", "There was a bad smell in the hallway."],
    "noise": ["Very noisy, could hear the street all night.", "Loud neighbours and thin walls."],
    "check_in": ["The robot check-in did not work and I waited ages.", "Could not get the door code to work at check in."],
    "staff": ["The receptionist was rude and unhelpful.", "No staff on site when we had a problem."],
    "facilities": ["No air conditioning and the lift was broken.", "No cups or kettle in the kitchen."],
    "room_condition": ["The bed was hard and the window would not close.", "The shower was broken and the room felt run down."],
    "value": ["Not worth the money for what you get.", "Overpriced for the condition of the room."],
    "location": ["Hard to find and far from the station."],
}
ROOMS = ["Standard Double Room (Ensuite)", "Superior Double Room (Ensuite)", "Standard Double Room with Private External Bathroom"]
COUNTRIES = ["Australia", "United Kingdom", "New Zealand", "Germany", "United States", "France", "Japan"]
TRAVELLERS = ["Solo traveller", "Couple", "Group of friends", "Family", "Business traveller"]
REPLY = "Thank you for your feedback. We have shared your comments with our team."

# Weakness weights per property: higher = more complaints of that kind (makes the demo interesting)
PROFILE = {
    "olympic-paddington": {"cleanliness": 3, "noise": 1, "check_in": 2, "facilities": 2, "room_condition": 2, "staff": 1, "value": 1, "location": 0},
    "venus-potts-point-sydney": {"cleanliness": 1, "noise": 4, "check_in": 1, "facilities": 1, "room_condition": 1, "staff": 1, "value": 1, "location": 0},
    "venus-surry-hills": {"cleanliness": 1, "noise": 1, "check_in": 1, "facilities": 1, "room_condition": 1, "staff": 3, "value": 1, "location": 0},
    "chateau-de-venus": {"cleanliness": 1, "noise": 1, "check_in": 1, "facilities": 2, "room_condition": 1, "staff": 1, "value": 2, "location": 0},
}


def make(rng: random.Random, slug: str, day: date, idx: int) -> Review:
    profile = PROFILE[slug]
    n_bad = rng.choices([0, 1, 2, 3], weights=[40, 30, 20, 10])[0]
    bad_topics = rng.choices(list(profile), weights=[profile[t] + 0.2 for t in profile], k=n_bad)
    bad_topics = list(dict.fromkeys(bad_topics))
    good_topics = rng.sample(list(GOOD), k=rng.choice([1, 2, 3]))
    liked = " ".join(rng.choice(GOOD[t]) for t in good_topics)
    disliked = " ".join(rng.choice(BAD[t]) for t in bad_topics) or None
    rating = max(1.0, min(10.0, round(9.2 - 1.8 * len(bad_topics) + rng.uniform(-1.2, 1.0), 0)))
    key = hashlib.sha1(f"demo-{slug}-{idx}".encode()).hexdigest()[:16]
    replied = disliked is not None and rng.random() < 0.6
    stay = day - timedelta(days=rng.randint(2, 20))
    nights = rng.choice([1, 1, 2, 3, 4])
    return Review(
        review_key=f"demo-{key}", property=slug, rating=rating, review_date=day,
        title=None if rng.random() < 0.4 else "Demo review", liked=liked, disliked=disliked, language="en",
        reviewer_country=rng.choice(COUNTRIES), traveller_type=rng.choice(TRAVELLERS), room_type=rng.choice(ROOMS),
        nights=nights, checkin_date=stay, checkout_date=stay + timedelta(days=nights),
        host_reply=REPLY if replied else None, helpful_votes=rng.choice([0, 0, 0, 1, 2]),
    )


def main() -> None:
    os.makedirs("data", exist_ok=True)
    if os.path.exists(OUT):
        os.remove(OUT)
    rng = random.Random(42)
    clock_now = datetime(2026, 11, 27, 8, 0, tzinfo=timezone.utc)
    store = ReviewStore(OUT, clock=lambda: clock_now)
    total = 0
    for prop in PROPERTIES:
        reviews, idx = [], 0
        for d in range(WEEKS * 7):
            day = TODAY - timedelta(days=d)
            for _ in range(rng.choices([0, 1, 2], weights=[45, 40, 15])[0]):
                reviews.append(make(rng, prop.slug, day, idx))
                idx += 1
        result = store.upsert_reviews(reviews)
        run = store.start_run(prop.slug, "full")
        store.finish_run(run, "ok", pages=max(1, len(reviews) // 10), new=result.new, updated=0, rejected=0, error=None)
        total += result.new
        print(f"{prop.name}: {result.new} synthetic reviews")
    print(f"Wrote {OUT} ({total} synthetic reviews). NOT real data.")


if __name__ == "__main__":
    main()
