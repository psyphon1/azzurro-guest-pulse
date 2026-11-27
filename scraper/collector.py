from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable
from zoneinfo import ZoneInfo

from scraper.config import HARD_MAX_PAGES, PAGE_SIZE
from scraper.errors import BlockedError, FetchError, PaginationError
from scraper.models import ParsedPage
from scraper.models import clean_text
from scraper.parse import ParseError
from scraper.store import ReviewStore

SYDNEY = ZoneInfo("Australia/Sydney")

# Reviews published around midnight can swap places across a page boundary; anything beyond this is a wrong sort.
ORDER_TOLERANCE_DAYS = 1

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
    since_days: int | None = None
    stop_reason: str | None = None   # last_page | no_new_reviews | page_cap | date_window (None when the run failed)

    @property
    def coverage_note(self) -> str:
        """Plain-English explanation shown in the CLI, ledger readers and the dashboard. Empty if complete."""
        if not self.truncated:
            return ""
        if self.stop_reason == "date_window":
            return (f"reviews from the last {self.since_days} days only; "
                    "older reviews were not collected (date window)")
        return (f"newest {self.collected} of {self.reported_total} reviews "
                f"(stopped at the {self.max_pages}-page limit; older reviews were not collected)"
                if self.reported_total else
                f"newest {self.collected} reviews (stopped at the {self.max_pages}-page limit; older reviews were not collected)")


def _safe_error(text: str) -> str:
    """Error text can carry remote-controlled content: strip escapes and newlines, bound the length."""
    return clean_text(text, 500)


def collect_property(slug: str, pages: Iterable[ParsedPage], store: ReviewStore, mode: str,
                     max_pages: int | None = None, since_days: int | None = None,
                     today: date | None = None) -> CollectionSummary:
    """Pull pages (newest first), store them, and record the outcome. Never raises on fetch problems,
    so one failing property cannot stop the others.

    ``max_pages`` is an explicit, recorded limit (newest first). When it is hit while Booking still has older
    reviews the run is marked ``truncated``: that is not an error, but it changes two checks. Older reviews must
    not be flagged "missing", and the drift check compares against what the cap allows, not the full total."""
    store.close_stale_runs(slug)
    run_id = store.start_run(slug, mode)
    summary = CollectionSummary(status="ok", max_pages=max_pages, since_days=since_days)
    stop = "last_page"       # unless something below says otherwise
    cutoff = None
    if since_days is not None:
        cutoff = (today or datetime.now(SYDNEY).date()) - timedelta(days=since_days)
    seen: set[str] = set()
    oldest_so_far: date | None = None

    try:
        for page in pages:
            if not page.reviews and not page.rejected:
                break  # past the last page
            if summary.pages >= HARD_MAX_PAGES:
                raise PaginationError(f"Server kept returning pages past the hard ceiling of {HARD_MAX_PAGES} pages; "
                                      "run stopped (the pages already saved were kept)")
            keys = {r.review_key for r in page.reviews}
            if keys and keys <= seen:
                raise PaginationError("Server repeated a page it had already sent (pagination loop); "
                                      "run stopped (the pages already saved were kept)")
            if page.reviews:
                newest_here = max(r.review_date for r in page.reviews)
                if oldest_so_far is not None and newest_here > oldest_so_far + timedelta(days=ORDER_TOLERANCE_DAYS):
                    raise FetchError("Reviews are not arriving in newest-first order (the sort did not apply), "
                                     "so the stop rules cannot be trusted; run stopped, pages already saved were kept")
                oldest_so_far = min(r.review_date for r in page.reviews) if oldest_so_far is None \
                    else min(oldest_so_far, min(r.review_date for r in page.reviews))
            summary.pages += 1
            summary.reported_total = page.reported_total or summary.reported_total
            result = store.upsert_reviews(page.reviews)
            store.quarantine(slug, page.rejected)
            summary.new += result.new
            summary.updated += result.updated
            summary.rejected += len(page.rejected) + result.conflicts
            seen.update(r.review_key for r in page.reviews)

            if mode == "incremental" and page.reviews and result.new < len(page.reviews):
                stop = "no_new_reviews"
                break  # newest-first: the first review we already have means everything further back is stored
            if cutoff is not None and page.reviews and max(r.review_date for r in page.reviews) < cutoff:
                stop = "date_window"
                break  # newest-first: this whole page is older than the window, so everything further back is too
            if max_pages is not None and summary.pages >= max_pages:
                stop = "page_cap"
                break  # the generator is lazy, so the browser is never asked for another page
    except BlockedError as exc:
        summary.status, summary.error = "blocked", _safe_error(str(exc))
    except (FetchError, ParseError) as exc:
        summary.status, summary.error = "failed", _safe_error(str(exc))
    except Exception as exc:  # a bug or a poisoned value must close the ledger, not leave a run 'running'
        summary.status, summary.error = "failed", _safe_error(f"Unexpected {type(exc).__name__}: {exc}")
    except KeyboardInterrupt:
        store.finish_run(run_id, "interrupted", summary.pages, summary.new, summary.updated,
                         summary.rejected, "Stopped by user (Ctrl+C); pages already saved were kept")
        raise

    summary.stored_total = store.count(slug)
    summary.collected = len(seen)
    summary.stop_reason = stop if summary.status == "ok" else None
    summary.truncated = (stop in ("page_cap", "date_window") and summary.status == "ok"
                         and (summary.reported_total is None or summary.collected < summary.reported_total))

    if mode == "full" and summary.status == "ok" and summary.pages == 0 and summary.stored_total > 0:
        # A page-less "complete" run for a property that already has reviews is a broken or hostile response,
        # not evidence that every review vanished.
        summary.status = "failed"
        summary.error = (f"Server returned no reviews at all, but {summary.stored_total} are already stored; "
                         "nothing was flagged as missing")

    if mode == "full" and summary.status == "ok":
        if summary.reported_total and stop != "date_window":   # a date window says nothing about the grand total
            expected = summary.reported_total
            if summary.truncated:
                expected = min(expected, max_pages * PAGE_SIZE)
            summary.drift = summary.collected < expected * (1 - DRIFT_TOLERANCE)
        if not summary.truncated and not summary.drift and stop != "date_window":
            store.mark_missing(slug, seen)  # only safe when we saw (nearly) everything Booking says it shows

    store.finish_run(run_id, summary.status, summary.pages, summary.new, summary.updated,
                     summary.rejected, summary.error, truncated=summary.truncated,
                     reported_total=summary.reported_total, max_pages=max_pages,
                     stop_reason=summary.stop_reason, since_days=since_days)
    return summary
