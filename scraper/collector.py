from dataclasses import dataclass
from typing import Iterable

from scraper.config import PAGE_SIZE
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
    truncated: bool = False   # stopped at the page cap while Booking still had older reviews
    max_pages: int | None = None
    collected: int = 0        # distinct reviews seen in this run

    @property
    def coverage_note(self) -> str:
        """Plain-English explanation shown in the CLI, ledger readers and the dashboard. Empty if complete."""
        if not self.truncated:
            return ""
        return (f"newest {self.collected} of {self.reported_total} reviews "
                f"(stopped at the {self.max_pages}-page limit; older reviews were not collected)"
                if self.reported_total else
                f"newest {self.collected} reviews (stopped at the {self.max_pages}-page limit; older reviews were not collected)")


def collect_property(slug: str, pages: Iterable[ParsedPage], store: ReviewStore, mode: str,
                     max_pages: int | None = None) -> CollectionSummary:
    """Pull pages (newest first), store them, and record the outcome. Never raises on fetch problems,
    so one failing property cannot stop the others.

    ``max_pages`` is an explicit, recorded limit (newest first). When it is hit while Booking still has older
    reviews the run is marked ``truncated``: that is not an error, but it changes two checks. Older reviews must
    not be flagged "missing", and the drift check compares against what the cap allows, not the full total."""
    store.close_stale_runs(slug)
    run_id = store.start_run(slug, mode)
    summary = CollectionSummary(status="ok", max_pages=max_pages)
    hit_cap = False
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
            if max_pages is not None and summary.pages >= max_pages:
                hit_cap = True
                break  # the generator is lazy, so the browser is never asked for another page
    except BlockedError as exc:
        summary.status, summary.error = "blocked", str(exc)
    except (FetchError, ParseError) as exc:
        summary.status, summary.error = "failed", str(exc)
    except KeyboardInterrupt:
        store.finish_run(run_id, "interrupted", summary.pages, summary.new, summary.updated,
                         summary.rejected, "Stopped by user (Ctrl+C); pages already saved were kept")
        raise

    summary.stored_total = store.count(slug)
    summary.collected = len(seen)
    summary.truncated = (hit_cap and summary.status == "ok"
                         and (summary.reported_total is None or summary.collected < summary.reported_total))

    if mode == "full" and summary.status == "ok":
        if not summary.truncated:
            store.mark_missing(slug, seen)  # only safe when we saw everything Booking shows
        if summary.reported_total:
            expected = summary.reported_total
            if summary.truncated:
                expected = min(expected, max_pages * PAGE_SIZE)
            summary.drift = summary.collected < expected * (1 - DRIFT_TOLERANCE)

    store.finish_run(run_id, summary.status, summary.pages, summary.new, summary.updated,
                     summary.rejected, summary.error, truncated=summary.truncated,
                     reported_total=summary.reported_total, max_pages=max_pages)
    return summary
