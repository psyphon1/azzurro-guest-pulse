from dataclasses import dataclass


@dataclass(frozen=True)
class Property:
    slug: str
    name: str
    url: str


PROPERTIES = [
    Property("olympic-paddington", "Olympic Hotel Paddington",
             "https://www.booking.com/hotel/au/olympic-paddington.html"),
    Property("venus-potts-point-sydney", "Potts Point",
             "https://www.booking.com/hotel/au/venus-potts-point-sydney.html"),
    Property("venus-surry-hills", "Central Sydney",
             "https://www.booking.com/hotel/au/venus-surry-hills.html"),
    Property("chateau-de-venus", "Darling Harbour",
             "https://www.booking.com/hotel/au/chateau-de-venus.html"),
]
BY_SLUG = {p.slug: p for p in PROPERTIES}

DB_PATH = "data/reviews.db"

# Booking.com returns 10 reviews per page.
PAGE_SIZE = 10
# Newest-first page limit per property per run (200 pages = up to 2,000 reviews). See docs/adr/002-page-cap.md.
DEFAULT_MAX_PAGES = 200

# A real page carries 10 cards. A response with more than this is hostile or broken, not a bigger page.
MAX_CARDS_PER_PAGE = 100

# Absolute ceiling on pages per run, whatever --max-pages says (and even when no cap is given): a server that never
# ends must not be able to keep a run alive forever. 1,000 pages = 10,000 reviews per hotel per run.
HARD_MAX_PAGES = 1000

# Only reviews from the last N days matter for weekly operations: stop at the first page that is entirely older.
DEFAULT_SINCE_DAYS = 365
