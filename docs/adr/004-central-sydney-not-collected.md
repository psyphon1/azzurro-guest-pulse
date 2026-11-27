# ADR 004: Central Sydney (venus-surry-hills) is not collected in this submission

Status: accepted. Follows ADR 003.

## What happened

Central Sydney (`venus-surry-hills`) was blocked: "Bot check did not clear and the reviews section never appeared". No
review from this hotel was stored. The operator reported two blocked attempts at the terminal. **The run ledger holds one**
(run 5, 2026-11-27 15:11:25 to 15:11:57, 32 seconds), so only that one is on the record; treat the second as reported, not
recorded.

Run 5 started the moment the Potts Point crawl (144 pages, 9.5 minutes) finished. Later, the hotel page was opened on its
own, outside a collection run. It loaded normally, showed 2,445 reviews and had the "Read all reviews" button, so the page
itself is fine and the scraper can reach it.

## The cause is not known

Candidate explanation: Booking.com's bot protection refused a connection that had just made a large number of requests.
Observations that fit: the failure came straight after a long crawl, and the page loaded normally when the connection had
been idle.

**An observation that contradicts it:** Darling Harbour started 0.2 seconds after Central Sydney's block ended
(15:11:58) from the same connection and ran 201 pages without being blocked. A connection-wide throttle would be expected to
refuse that hotel as well. So either the block was specific to this hotel's page or this attempt (for example a slow or
different bot challenge for that property), or throttling is not the explanation at all.

Nothing was tested under controlled conditions (idle connection, this hotel alone, with the new safeguards). Do not read the
three collected hotels as proof that the hotel can be collected, and do not repeat "throttling" as a fact.

## What the system does for a hotel with no data

- The run ledger (`scrape_runs`) shows the hotel's latest run as `blocked`, with the message above. At the time of writing
  the ledger holds one `blocked` entry for this hotel.
- The dashboard says so at the top ("Central Sydney: no reviews collected yet. Booking.com blocked our automatic check ...
  It is not included in any number on this page"), gives the hotel a card marked "No data", and adds "Based on 3 of 4
  hotels" under the headline figures, trends, charts and feed.
- The dashboard never makes up numbers for it. The hotel is left out of every average, count and chart, and the code only
  counts reviews that exist in the database. This was checked by loading the dashboard on the final database: no errors.
- The README, the requirements traceability table and the sample files all say it is not collected.

## What was decided and why

Skip Central Sydney for this submission and submit three of the four hotels.

1. **Time.** Each full attempt needs the connection to rest first and may need to be repeated. Retrying until it works
   was not possible in the time available.
2. **Honest partial beats hidden failure.** A visible "not collected, blocked" is better than a fourth hotel filled with
   anything that was not really collected, or silence about the gap. Waiting on a hotel that stays blocked would also have
   delayed the other three, which are usable.
3. **Nothing is lost by waiting.** The collector is safe to re-run later: stored reviews are never duplicated.

## How to collect it later

```bash
python -m scraper.run --property venus-surry-hills --mode full
python -m insights.pipeline --db data/reviews.db
```

Advice:

- Run it **alone first**, not as part of `--property all`. Resting the connection first is a precaution, not a proven fix
  (see above).
- The new safeguards from ADR 003 apply: the pause between hotels (`--pause`, only relevant when several hotels run), one
  retry after a 3 to 4.5 minute wait, and a clear "blocked" ending if the page vanishes early.
- If it is still blocked, try again later. How long to wait is unknown; a few hours is a guess, not something Booking.com
  publishes. If it is blocked repeatedly on an idle connection, throttling is probably not the cause.
- With a few thousand reviews the default 365-day window and 200-page cap apply (ADR 002 and ADR 003). The hotel page
  reported 2,445 reviews when it was checked on its own.
- After a successful run, re-export the sample files (`python scripts/export_sample.py`, see the README) so the shared
  snapshot includes the hotel.

## Consequence for the submission

Three of four hotels have data: Olympic Hotel Paddington, Potts Point and Darling Harbour. Two of those are partial
(see the README for the exact counts). Anything the dashboard, the sample files or the classifier evaluation shows is
about those three. The classifier evaluation also never saw a Central Sydney review.
