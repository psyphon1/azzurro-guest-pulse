class FetchError(Exception):
    """Getting a page failed (timeout, network, unexpected page). Safe to record and move on."""


class BlockedError(FetchError):
    """The site refused us (bot check, HTTP 400/403/429). Do not retry in a loop."""
