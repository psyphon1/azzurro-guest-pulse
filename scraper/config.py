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
