# ADR 001: How reviews are collected

Status: accepted for now, to be revisited after the fetcher spike.

## What we found (exploration, not test-driven)

Booking.com has no public API for us, but the property page itself loads reviews
from a GraphQL call (`operationName: "ReviewList"`, POST). Observed on Olympic Hotel Paddington:

- 10 reviews per call, paged with `skip`; sort options include `NEWEST_FIRST`.
- Each review has a stable ID (`reviewUrl`), score, Unix timestamp, separate
  liked / disliked text, language, room, stay dates, traveller type and the hotel's reply.
- The response also carries Booking's own sub-scores (cleanliness, staff, value, ...) and totals.
- The site uses AWS WAF bot protection (`challenge.js`, `telemetry` calls). The GraphQL call
  uses a persisted-query hash and session values, so replaying it from plain HTTP is likely
  to be refused and fragile.

## Decision

1. Parsing is separated from fetching. `scraper/parse.py` is a pure function over the JSON
   and is fully covered by tests on saved fixtures (no network in tests).
2. Fetching will use a real browser (Playwright) at low volume and read the `ReviewList`
   responses as the page loads them. We do not forge tokens or try to bypass bot protection.
3. If the site blocks even that, we stop and document it. The fallback is importing a CSV
   exported from the Booking.com Extranet, which hotel owners can access.

## Data decisions

- Dedup key: `reviewUrl`.
- Reviewer name and avatar are never stored (personal data, not needed).
- Dates are converted to Australia/Sydney local dates.
- Cards that fail validation are quarantined, not dropped silently.
- Total review count is read from the response to cross-check how many we collected.

## Open questions

- `reviewsCount` was 74 while the filters said "All (133)". Unknown meaning; we use the filter total for now.
