# ADR 002: Only the newest 200 pages of reviews are collected per hotel

Status: accepted.

## Context

Hotels differ a lot in size. Olympic Paddington has 133 reviews (14 pages). Potts Point has 1,440 (144 pages).
Darling Harbour (Chateau de Venus) has far more than 2,000. Booking.com returns 10 reviews per page, and each
extra page costs a browser click plus a 2 to 5 second polite pause.

## Decision

Each run reads reviews newest first and stops after `--max-pages` pages (default 200, which is up to
2,000 reviews). The cap is explicit, recorded and shown to the user. It is not a silent safety stop.

## Why

1. **Relevance.** The dashboard answers "what is going wrong now?". Weekly and 4-week views only need recent
   reviews. A review from three years ago says little about the current state of a hotel.
2. **Politeness and blocking risk.** The site has bot protection. Each extra page is another request from
   an automated browser. Capping the volume keeps one run short (200 pages is about 15 minutes) and lowers the
   chance of being blocked.
3. **Reliability.** The longer a single browser session runs, the likelier a layout hiccup or timeout.
   Shorter, bounded runs fail less and are cheaper to retry.
4. **Predictable cost.** A bounded run time makes daily scheduling realistic.

## What changes because of a cap (and how it is handled)

A capped run is not a failure, but it is not complete either. Two checks must change, otherwise the cap would
cause false alarms or silent data damage:

| Check | Without special handling | With the cap |
|---|---|---|
| Drift check (collected vs Booking's total) | Always alarms: 2,000 of 3,000 looks like 33% missing | Compared with what the cap allows: `min(total, max_pages x 10)`. Still alarms if far fewer arrive than the cap implies. |
| "Missing review" flag after a full run | Would mark every older review we already hold as missing | Skipped for truncated runs. We did not look at the old pages, so we know nothing about them. |
| Run status | Looks like a normal `ok` | `ok` with `truncated = 1`, plus `max_pages` and `reported_total` recorded in `scrape_runs` |

A run counts as truncated only when it hit the cap AND we collected fewer reviews than Booking.com reports.
A hotel that happens to have exactly as many reviews as the cap allows is not truncated.

## How staff see it

- CLI prints `TRUNCATED: newest 2000 of 3120 reviews (stopped at the 200-page limit; older reviews were not collected)`.
- Dashboard shows a "Not every review is included" notice and a Coverage column in Data health.
- Weekly numbers for recent weeks are complete. Long-term history for capped hotels is not.

## Consequences and limits

- Trend charts that reach back further than the oldest collected review will look empty or short for capped hotels.
  The notice says so.
- Averages over "all time" for a capped hotel describe only the collected window.
- To collect more, raise the cap: `python -m scraper.run --property chateau-de-venus --mode full --max-pages 400`.
  Re-running is safe: reviews already stored are not duplicated.
- Because incremental runs stop at the first page with nothing new, daily updates are unaffected by the cap.
