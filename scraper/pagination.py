"""When is a missing 'Next page' button really the end of the reviews?

Lesson from Potts Point: the run stopped at exactly 144 full pages (1,440 reviews) while Booking.com reported
2,386, and it was recorded as a normal 'ok' ending. A button that vanishes can mean the list ended, but it can
also mean the page was throttled or still re-rendering. This pure function makes the call, so it is unit tested
without a browser. The browser layer only supplies the facts.
"""
from scraper.config import PAGE_SIZE

# How many times to wait and look again before believing a suspicious ending.
MAX_RETRIES = 3
# A real ending: we hold at least this share of the total Booking reports.
COMPLETE_SHARE = 0.90


def next_step(last_page_size: int, collected: int, reported_total: int | None,
              next_available: bool, retries_used: int) -> str:
    """Returns 'continue', 'end', 'retry' (wait and look again) or 'ended_early' (give up, report it)."""
    if next_available:
        return "continue"
    if last_page_size < PAGE_SIZE:
        return "end"            # a short (or empty) last page is how a list really ends
    if not reported_total or reported_total < 1:
        return "end"            # nothing to compare with, so we cannot call it suspicious
    if collected >= reported_total * COMPLETE_SHARE:
        return "end"            # full page, but we already hold (nearly) everything Booking reports
    return "retry" if retries_used < MAX_RETRIES else "ended_early"
