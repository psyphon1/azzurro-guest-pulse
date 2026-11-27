class FetchError(Exception):
    """Getting a page failed (timeout, network, unexpected page). Safe to record and move on."""


class BlockedError(FetchError):
    """The site refused us (bot check, HTTP 400/403/429). Do not retry in a loop."""


class PaginationError(FetchError):
    """The server never ends or keeps repeating itself. The run is stopped and recorded as failed."""


class StoreError(Exception):
    """The database cannot be used (locked by another process, not a SQLite file, damaged, unwritable).
    Raised with a plain-English message instead of a raw sqlite3 traceback."""


class EndedEarlyError(BlockedError):
    """The list stopped offering pages although Booking.com reports many more reviews (usually throttling).
    Recorded as 'blocked' so the dashboard warns staff; pages already saved are kept."""
