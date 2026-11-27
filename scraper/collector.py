from dataclasses import dataclass
from typing import Iterable

from scraper.errors import BlockedError, FetchError
from scraper.models import ParsedPage
from scraper.parse import ParseError
from scraper.store import ReviewStore

# If a full run collects fewer than this share of the total Booking reports, something is wrong.
DRIFT_TOLERANCE = 0.10


@dataclass
class CollectionSummary:
    status: str  # ok | blocked | failed
    pages: int = 0
    new: int = 0
    updated: int = 0
    rejected: int = 0
    reported_total: int | None = None
    stored_total: int = 0
    drift: bool = False
    error: str | None = None


def collect_property(slug: str, pages: Iterable[ParsedPage], store: ReviewStore, mode: str) -> CollectionSummary:
    """Pull pages (newest first), store them, and record the outcome. Never raises on fetch problems,
    so one failing property cannot stop the others."""
    run_id = store.start_run(slug, mode)
    summary = CollectionSummary(status="ok")
    seen: set[str] = set()

    try:
        for page in pages:
            if not page.reviews and not page.rejected:
                break  # past the last page
            summary.pages += 1
            summary.reported_total = page.reported_total or summary.reported_total
            result = store.upsert_reviews(page.reviews)
            store.quarantine(slug, page.rejected)
            summary.new += result.new
            summary.updated += result.updated
            summary.rejected += len(page.rejected)
            seen.update(r.review_key for r in page.reviews)

            if mode == "incremental" and result.new == 0:
                break  # newest-first: nothing new on this page means nothing new further back
    except BlockedError as exc:
        summary.status, summary.error = "blocked", str(exc)
    except (FetchError, ParseError) as exc:
        summary.status, summary.error = "failed", str(exc)

    summary.stored_total = store.count(slug)

    if mode == "full" and summary.status == "ok":
        store.mark_missing(slug, seen)
        if summary.reported_total:
            collected_share = len(seen) / summary.reported_total
            summary.drift = collected_share < (1 - DRIFT_TOLERANCE)

    store.finish_run(run_id, summary.status, summary.pages, summary.new, summary.updated,
                     summary.rejected, summary.error)
    return summary
