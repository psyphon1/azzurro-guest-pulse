# ADR 003: Date window, throttling safeguards and honest endings

Status: accepted. Refines ADR 002.

## What happened in the first full runs

| Hotel | Result | Cause |
|---|---|---|
| Potts Point | 144 pages, 1,440 stored, Booking.com reported 2,386, flagged `DRIFT` | The "Next page" button vanished after a full page and the run ended as a normal `ok`. A real last page is almost never full. |
| Central Sydney | blocked twice ("Bot check did not clear") | Both attempts started straight after a long crawl from the same connection. The page loads fine when opened alone. Most likely throttling. |
| Darling Harbour | 201 pages, 2,010 stored of 4,305 | The old internal 200-page safety stop. Reviews reached back about 20 months. |

Two lessons. First, the drift check worked: it caught an incomplete run that would otherwise have looked fine.
Second, our own code had mistaken a missing button for the end of the list.

## Decisions

1. **A missing "Next page" button is not proof of the end** (`scraper/pagination.py`). It is trusted as the end only if
   the last page was short, or we already hold at least 90% of what Booking.com reports, or there is nothing to compare
   with. Otherwise the scraper waits 5 seconds and looks again, up to 3 times, then stops with `EndedEarlyError`, recorded
   as `blocked` with a message saying how many reviews were read and that throttling is the likely cause.
2. **Date window instead of a page count as the main limit** (`--since-days`, default 365). Operations needs recent
   reviews, and reviews from two or three years ago add runtime and risk but no insight. The run stops at the first page
   that is entirely older than the window. The page cap (ADR 002) stays as a hard ceiling. `--no-date-window` reads further back.
3. **Pauses and one retry** (`--pause`, default 60 s, randomised up to double, between hotels; one retry after a 3 to
   4.5 minute back-off when a hotel is blocked). This lowers the load that triggers throttling and recovers from a
   short block without anyone watching.
4. **Stop reason in the ledger** (`last_page`, `no_new_reviews`, `page_cap`, `date_window`) plus `since_days`, so anyone
   can see why a run ended.
5. **Order guard.** If pages do not arrive newest-first (for example the sort dropdown silently stayed on "Most relevant"),
   the date window and the "nothing new" rule would stop in the wrong place without any error. The collector now fails
   the run loudly when a later page contains reviews more than a day newer than everything seen so far, and the browser
   layer checks that "Newest first" really applied.

## What a date-window run does differently

Like a capped run, it is not a failure but it is not complete history: it never flags older stored reviews as missing,
and it skips the drift check against Booking.com's grand total (the total says nothing about a 365-day window).
Drift protection is still active through the early-ending check in decision 1.

## Limits

- Throttling is a hypothesis based on three observations, not something Booking.com confirmed.
- The retry waits minutes; a hotel that stays blocked is reported and left for the next scheduled run.
- Reviews older than the window that are already stored stay stored. Weekly metrics ignore them.
