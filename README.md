# Guest Pulse

*The pulse of what guests say about Azzurro Hotels on Booking.com.*

Collects public Booking.com guest reviews for four Azzurro Hotels properties and turns them into a
dashboard that operations staff can read on a Monday morning: how each hotel scored this week, what
changed since last week, what guests keep complaining about, and which bad reviews still have no reply.

| Property | Booking.com page (also the `--property` value) | Collected in this submission |
|---|---|---|
| Olympic Hotel Paddington | olympic-paddington | Yes, complete (133 reviews) |
| Potts Point | venus-potts-point-sydney | Partly: 1,440 stored of 2,386 reported |
| Central Sydney | venus-surry-hills | **No.** Blocked, skipped (see below) |
| Darling Harbour | chateau-de-venus | Partly: 2,010 stored of 4,305 reported |

**Read this first: this submission has data for 3 of the 4 hotels, and two of those three are partial.**

- **Central Sydney has no reviews.** Both collection attempts were blocked by Booking.com's bot check, and it was
  decided not to keep retrying in the time available. The dashboard lists it as blocked and shows no numbers for it. Why,
  and how to collect it later: [docs/adr/004-central-sydney-not-collected.md](docs/adr/004-central-sydney-not-collected.md).
- **Potts Point** is partial: the review list ended early (the "Next page" button disappeared), so the oldest reviews
  (before 2023-11-28) are missing.
- **Darling Harbour** is partial: the first run stopped at an old 200-page limit, so reviews before 2025-01-31 are missing.
- Counts were read from `data/reviews.db` on 2026-11-27 (see [What was collected](#what-was-collected)). Recent weeks, which
  are what the dashboard is for, are covered for the three collected hotels.

Booking.com offers no API access, so reviews are collected through a real browser (see
[Review collection](#review-collection)). Everything else (storage, topic analysis, metrics, dashboard)
is independent of how the reviews arrive.

## Quick start

Developed on Python 3.15 and also tested on 3.13 (all tests pass on both). On Python 3.11 everything works except
`scripts/export_sample.py` (3 of its tests fail), so use 3.13 or newer. Uses Chromium via Playwright. Run every command
below from the project folder (the one containing this file): the dashboard reads `.streamlit/config.toml` from the
folder you start it in. The commands are for macOS and Linux; on Windows activate the environment with
`.venv\Scripts\activate`.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

# 1. Collect reviews (opens a visible browser window; leave it alone while it runs).
#    10 reviews per page with a 2-5 s pause: about 1.5 min for 133 reviews, about 5 min for 540.
#    Between hotels it rests 60 to 120 s, and a hotel with a year of busy history can take 10+ minutes,
#    so budget roughly half an hour for all four. To try one hotel first, use its slug from the table
#    above, e.g. --property olympic-paddington
python -m scraper.run --property all --mode full

# 2. Tag reviews with topics
python -m insights.pipeline --db data/reviews.db

# 3. Open the dashboard
streamlit run dashboard/app.py
```

No internet or time to scrape? Try the dashboard on clearly labelled synthetic data:

```bash
python scripts/make_demo_db.py
python -m insights.pipeline --db data/demo.db
REVIEWS_DB=data/demo.db streamlit run dashboard/app.py     # shows a "DEMO DATA" banner
```

Streamlit prints a local address (normally http://localhost:8501); open it in a browser. If the database file does not
exist yet, the dashboard says so and shows these same commands instead of failing.

Run the tests: `python -m pytest -q` (no network needed; about 1,030 tests, around 40 seconds).

Browser tests (real Chromium driving the real dashboard, watching the console, network and server log):
`python -m pytest -m e2e tests/e2e`. A requirements walkthrough that checks what the screen shows against counts read
straight from the database (feed totals, filters, CSV, hotels, data health, phone width) is
`python scripts/browser_audit.py` (screenshots go to `data/audit_shots/`).

### Keeping it up to date

| When | Command | What it does |
|---|---|---|
| Daily | `python -m scraper.run --property all --mode incremental` | Reads newest reviews first and stops at the first page with nothing new. Usually 1 page per hotel; the time per hotel (a browser start, the bot check, one page) has not been measured live, so expect tens of seconds. |
| Weekly | `python -m scraper.run --property all --mode full` | Re-reads newest first until the 365-day window or the page limit ends the run (see below). Picks up edited reviews and new hotel replies inside that range. It only flags reviews that disappeared and checks the count against what Booking.com reports when the run reaches the end of the list, which the default window normally prevents; add `--no-date-window` for that (slower). |
| After either | `python -m insights.pipeline --db data/reviews.db` | Tags only new or changed reviews. Safe to run repeatedly. |

Nothing schedules itself. Because a visible browser is needed (see limitations), the simplest setup is a
cron job or macOS launchd task on a machine that has a screen session.

Environment variable `REVIEWS_DB` points the dashboard at a different database (default `data/reviews.db`).

## Architecture

```
 Booking.com page
        |  real browser (Playwright), reads the "ReviewList" responses the page itself loads
        v
 scraper/browser.py  --->  scraper/parse.py  --->  scraper/collector.py  --->  SQLite  data/reviews.db
   (fetch, pagination)     (validate, anonymise)    (dedup, stop rule,          reviews, scrape_runs,
                                                     drift check, run ledger)    quarantine
                                                                                   |
                                      insights/classify.py + pipeline.py  <--------+
                                      (topic tags with evidence)  ---> review_topics
                                                                                   |
                                      insights/metrics.py  (weekly KPIs, trends, insight sentences)
                                                                                   |
                                      dashboard/app.py  (Streamlit, for non-technical staff)
```

| Folder | Responsibility |
|---|---|
| `scraper/` | Getting reviews: `browser.py` (live site), `parse.py` (pure JSON to validated reviews), `store.py` (SQLite, dedup, run ledger), `collector.py` (paging policy and failure handling), `run.py` (CLI) |
| `insights/` | `topics.py` (taxonomy), `classify.py` (keyword classifier), `pipeline.py` (writes `review_topics`), `metrics.py` (all numbers the dashboard shows) |
| `dashboard/` | Streamlit UI only. It calls `insights.metrics` and never recomputes a metric itself. |
| `tests/` | Offline tests on saved, anonymised fixtures. |
| `docs/` | `assumptions.md` (definitions), `contracts.md` (module interfaces), `evaluation.md` (classifier accuracy), `spot-check.md` (a 15-minute sheet for a human to check the accuracy labels), `deploy.md` (putting a sample-data demo online), `adr/` (decisions, including why Central Sydney is not collected), `security/` (red-team findings), `requirements-traceability.md` (requirement-by-requirement status and open gaps) |
| `scripts/` | `make_demo_db.py` (synthetic demo data), `evaluate_classifier.py` (score the classifier), `make_gold_sample.py` and `export_sample.py` (see Sample data), `backfill_coverage.py` (see Coverage backfill), and `spike_*.py` (throwaway investigation scripts, kept as a record, not product code) |

Design choices worth knowing:

- **Parsing is separate from fetching.** The parser is a pure function over JSON, so the part most likely
  to break when Booking.com changes is also the part that is fully testable offline.
- **Fetching is one swappable layer.** Anything that yields parsed pages can feed the collector,
  e.g. a CSV export from the Booking.com Extranet.
- **One definition per concept.** Sentiment bands live in `insights/metrics.py` only; topic IDs in
  `insights/topics.py` only.

## Review collection

### What we found

Opening a property page and clicking "Read all reviews" makes the page call Booking.com's own GraphQL
endpoint (`operationName: ReviewList`), 10 reviews at a time. Each review includes a stable review ID,
score, publish date, separate "liked" and "disliked" text, language, room type, stay dates, traveller
type and the hotel's reply. This was found by inspecting the browser's network traffic, then confirmed
on the live page. Details and the reasoning are in `docs/adr/001-collection-method.md`.

### Method

1. Open the property page in Chromium. The site shows an AWS WAF "checking your browser" page that clears
   itself after a few seconds in a normal browser. We wait for it. We do not forge tokens, spoof
   fingerprints or solve challenges.
2. Open the reviews panel, sort by "Newest first", and read each `ReviewList` response the page loads
   while clicking "Next page" (2 to 5 s random pause between pages).
3. Each response is validated and stored. Reviewer names and avatars are discarded at parse time.

### Reliability and data quality controls

| Risk | Control |
|---|---|
| Duplicates | Booking.com's review ID is the primary key. Re-running changes nothing: test `test_saving_the_same_reviews_twice_creates_no_duplicates`, and a live repeat full run of Olympic Paddington is on record in the run ledger (run 3: 14 pages read, 0 new reviews stored). |
| Edited reviews, new hotel replies | Content hash per review. A changed hash updates the row, keeps `first_seen`, and counts as `updated`. |
| Layout or API change | Parser raises `ParseError("layout probably changed")` instead of returning "no reviews". The run is recorded as `failed` with that message. |
| One bad review | Fails validation (rating outside 1 to 10, bad date, missing ID): goes to a `quarantine` table with the reason. The rest of the page is kept. |
| Silent partial collection | After a full run that reads to the end of the list (or to the page cap), the number collected is compared with the total Booking.com reports. A gap above 10% sets a `DRIFT` flag and a non-zero exit code. This check is skipped when the 365-day window ends the run, because the grand total says nothing about a one-year window. A "Next page" button that vanishes early is caught separately and recorded as `blocked`. |
| Blocking | A 400/403/429 or non-JSON reply raises `BlockedError`. The run stops for that hotel (no retry loop) and is recorded as `blocked`. |
| One hotel failing | Failures are recorded, not raised. The other hotels still run. |
| Process killed mid-run | The next run closes stale `running` entries as `interrupted`. Ctrl+C is recorded too. Pages already saved are kept. |
| Reviews removed from Booking | Flagged with `missing_since` after a full run that reached the end of the list, never deleted. Not done for runs ended by the date window or the page cap. |
| Stale data shown as fresh | The dashboard shows last successful update per hotel and warns after 48 hours or on a failed/blocked run. |

### What was collected

One run per hotel on 2026-11-27, from the run ledger and the `reviews` table of `data/reviews.db`:

| Hotel | Stored | Booking.com reports | Oldest to newest review | Why it is not complete |
|---|---|---|---|---|
| Olympic Hotel Paddington | 133 | 133 | 2026-07-06 to 2026-11-27 | Complete. |
| Potts Point | 1,440 | 2,386 | 2023-11-28 to 2026-11-27 | The list ended early after 144 full pages; the missing 946 are the oldest reviews. The drift check caught it (`DRIFT`). |
| Central Sydney | 0 | 2,445 (seen when the page was opened alone) | none | Blocked, not collected. [ADR 004](docs/adr/004-central-sydney-not-collected.md). |
| Darling Harbour | 2,010 | 4,305 | 2025-01-31 to 2026-11-27 | An old internal 200-page stop; reviews before 2025-01-31 are missing. |

3,583 reviews are stored in total. The two partial hotels were collected before the date window, the page-cap record
and the ledger coverage fields existed, so their coverage was written into the ledger afterwards (next section). In all
three cases the newest reviews, the ones weekly operations looks at, are present.

### Coverage backfill (`scripts/backfill_coverage.py`)

Runs collected before coverage tracking existed have no record of being partial, so the dashboard would show them as
complete. `scripts/backfill_coverage.py` fixes that after the fact: you give it the hotel, Booking.com's reported total,
why the run stopped (`page_cap` or `ended_early`) and where those numbers came from, and it marks that hotel's latest
successful run as partial. The evidence text is stored in the ledger, so the record says it was added later and from what.
It refuses to overwrite coverage the scraper recorded itself. It never touches the reviews table. It was used for Potts Point and Darling Harbour, with
the numbers printed in the console output of the first runs. Example:
`python scripts/backfill_coverage.py --db data/reviews.db --property venus-potts-point-sydney --reported-total 2386 --stop-reason ended_early --evidence "console output of the 27 Nov run"`.

### Date window and page limit

Reviews are read newest first. A run stops at the first page that is entirely older than **365 days**
(`--since-days`, `--no-date-window` to disable), because weekly operations only needs recent reviews. Pauses of
60 to 120 seconds separate hotels (`--pause`), and a blocked hotel is retried once after a few minutes. See
`docs/adr/003-date-window-and-throttling.md` for what happened in the first runs and why.

### Page limit for very large hotels

Reviews are read newest first and each hotel is capped at **200 pages (up to 2,000 reviews) per run**
(`--max-pages`, default 200). Darling Harbour has well over 2,000 reviews, so for that hotel older reviews are
deliberately not collected. Why: recent reviews are what weekly operations need, long sessions raise the risk of
being blocked, and a bounded run keeps daily scheduling realistic.

The cap is explicit, not silent. The run ledger records `truncated`, `max_pages` and `reported_total`; the CLI
prints a `TRUNCATED` line; the dashboard shows a "Not every review is included" notice and a Coverage column.
A capped run does not flag older stored reviews as missing and does not raise a false drift alarm. Details and
trade-offs: `docs/adr/002-page-cap.md`.

### Known limitations of collection

- **Central Sydney was not collected** (blocked, then skipped on purpose). The cause is unknown: throttling was the first
  guess, but another hotel ran unblocked a fraction of a second later, and the page loaded normally when opened alone later
  (ADR 004). Potts Point and Darling Harbour are partial, as above.
  A claim like "the average for Darling Harbour" therefore covers its newest 2,010 reviews only.
- **A visible browser window is required.** Headless Chromium receives HTTP 400 "Request not supported"
  from the review endpoint (observed during development). We did not try to disguise headless mode.
  Running on a server therefore needs a virtual display, or a different source such as an Extranet export.
- **Scraping may breach Booking.com's terms of service.** This tool reads only public pages, at low
  volume (one request per 10 reviews with a 2 to 5 s pause: 14 requests for a hotel with 133 reviews), for internal analysis. The proper long-term source
  is first-party data (below).
- **It will break eventually.** Selectors (`data-testid` values) and the response shape belong to
  Booking.com. Drift and layout checks are designed to make a break loud, not to prevent it.
- **Retries are limited.** Opening the reviews panel is retried 3 times. There is no exponential backoff
  on every request; a hard failure ends that hotel's run and is recorded.
- Booking.com may show only a subset of reviews, and review dates are publish dates, not stay dates.
- Incremental runs do not see edits to old reviews; the weekly full run does.

### Recommended next step: stop scraping

Azzurro owns these properties, so the reviews already belong to Azzurro. The Booking.com Extranet can
export them, and Booking.com connectivity partners (channel managers) offer a review feed. Because
fetching is isolated in `scraper/browser.py`, swapping it for a CSV import or an API client does not
change storage, insights or the dashboard.

### Sample data

Two files hold a snapshot so the dashboard can be shown without scraping:

- `data/sample_reviews.csv`: 733 rows, readable in Excel. The newest 300 reviews of Potts Point and of Darling Harbour, and
  all 133 of Olympic Hotel Paddington. It has date, hotel, score, room, traveller type, country, title, liked and disliked
  text, the hotel reply and the topic tags. No reviewer identity; e-mail addresses and phone numbers are masked.
- `data/sample/reviews_sample.db`: the same 733 reviews with their topic tags, so the dashboard runs on it:
  `REVIEWS_DB=data/sample/reviews_sample.db streamlit run dashboard/app.py`. It carries a "SAMPLE DATA" banner.

Central Sydney is not in either file. Because only the newest 300 per hotel are exported, the sample covers a shorter
period than the full database (Potts Point from 2025-06-04, Darling Harbour from 2026-03-12, both to 2026-11-27).

To regenerate after a new collection and pipeline run: `python scripts/export_sample.py --per-property 300`. It opens the
live database read-only and refuses to overwrite it. The CSV can be committed as is. The git-ignore rules keep
`data/sample/reviews_sample.db` out of the repository until you add it on purpose (`git add -f`, see `docs/deploy.md`),
because it holds real public review text. The live database is git-ignored. Needs Python 3.13 or newer (see Quick start).

## Insights

### Topics

Each review is classified into eight operational topics: cleanliness, check-in experience, staff
behaviour, noise, facilities, location, room condition and value for money.

Method (`insights/classify.py`): Booking.com already separates what guests liked from what they disliked,
so polarity comes from the field. Text in "liked" gives a positive mention, text in "disliked" a negative
one. Each sentence is matched against a keyword list per topic (word boundaries, case-insensitive), with
simple negation handling ("not dirty", "no issues with noise"). Every tag stores the exact sentence that
triggered it, and the dashboard shows it, so staff can see why a review was tagged.

Why keywords and not an AI model: it is free, deterministic, runs offline, and every decision can be
explained. The table that stores tags has a `method` column so an AI classifier can be added later
without changing anything downstream.

### How accurate is it?

Scored against 100 real reviews labelled independently (a separate annotator that never saw the classifier), on a
held-out half that was not used for tuning: **precision 0.84, recall 0.76, F1 0.80**. Weakest topic: room condition
(F1 0.65). Details, the tuning that was done and the caveats (100 reviews, English only, one AI annotator, no Central
Sydney reviews) are in `docs/evaluation.md`. The labels have not been checked by a person yet: `docs/spot-check.md` is a
sheet of 20 cases that takes about 15 minutes. An earlier self-labelled set scored higher (F1 0.95) and
should be ignored as evidence of real accuracy.

Known weaknesses:

- **English only.** About 20% of real reviews are in other languages (Spanish, Chinese, Japanese, French, ...).
  They get no topic tags and the dashboard says how many were not analysed. Booking.com's own rating, date
  and review counts still include them.
- **Sarcasm is not detected** ("GOING OUT THE DOOR." typed in the "liked" box on a 1/10 review).
- Guests sometimes put complaints in the "liked" box or the reverse, which flips polarity.
- Negation handling is a heuristic. Overlapping keywords ("broken", "shower") cause over-tagging.
- The review title is not classified.

### Numbers on the dashboard

Definitions are in `docs/assumptions.md`:

- **Week:** Monday to Sunday, Australia/Sydney time. Dates are publish dates.
- **Bands:** score 8 or more is positive, 5 to under 8 mixed, under 5 negative. These thresholds are
  constants in one place (`insights/metrics.py`).
- **Guest score** is the simple average of collected reviews and may differ from the score Booking.com
  displays, which uses its own weighting.
- **Percentages always come with counts**, and a "small sample" warning appears under 5 reviews.
- **Topic percentages use reviews with written comments as the base.** About 4 in 10 real reviews are
  rating-only and cannot mention a topic, so counting them would understate every problem. The dashboard
  says how many reviews had no comment.

## Dashboard

Hotel and time-period filters (latest full week, last week, last 4 or 12 weeks, custom dates) are in the sidebar.
For a non-technical reader, top to bottom: data freshness, "this week at a glance" (plain-English
insights, most important first), guest score against last week, a card per hotel, weekly trends of score
and of positive/mixed/negative counts, top complaint (or praise) topics with a hotel-by-topic grid, then
a review feed with filters (hotel, dates, topic, negative only, no hotel reply yet, has comment, text
search), CSV export and a "How to read this" explanation.

Not verified: layout on small phone screens and the CSV download button were not exercised in an automated test.

## Security and privacy

Review text is untrusted input: any guest can write a review, and the remote site could return anything. Two
adversarial reviews were carried out, one on collection and storage, one on presentation and analysis. Each finding
was reproduced as a failing test first, then fixed. Full tables, including what was already safe and the remaining
risks, are in `docs/security/scraper.md` and `docs/security/dashboard.md`.

Things that matter most:

- Reviewer names and avatars are never stored. E-mail addresses and phone numbers that guests type into review text
  are masked in the dashboard and in CSV exports (best effort).
- A review whose ID already belongs to another hotel is refused instead of overwriting it (found in review, critical).
- Malformed or hostile responses (wrong types, huge text, absurd dates, endless pages) end in a recorded, explained
  failure and never crash the run or fill the database.
- The browser may only open `https://www.booking.com/hotel/<country>/<name>.html`, uses a throw-away profile
  (no cookies or tokens on disk) and refuses downloads and permissions.
- The dashboard opens the database read-only, escapes all review text, guards CSV exports against spreadsheet
  formula injection and bounds search and classifier input.
- No secrets are required to run the project. `.env` and live databases are git-ignored, and a regression test scans
  tracked files for secret-looking strings. Dependencies are pinned and were audited with `pip-audit` (no known issues
  at the time of writing).

Remaining risks to know about: Streamlit has no login, so run it on localhost or behind a proxy or VPN, and start it
from the project root so `.streamlit/config.toml` applies. A lying but well-formed server cannot be detected locally.

## Assumptions

- Reviewer names are personal data and are not needed, so they are never stored.
- "Negative review" is decided by score band. A written complaint inside a high-scoring review is still
  tagged by topic but does not count as a negative review.
- A hotel opened recently may have few reviews per week, so week-to-week changes are noisy. The dashboard
  shows counts and warnings instead of hiding that.

## Roadmap

1. Replace scraping with an Extranet export or channel-manager feed.
2. Multilingual classification (an LLM tier writing to the same `review_topics` table, cached per review).
3. Weekly email or chat digest, so staff do not need to open a dashboard.
4. Alert when a hotel's weekly score falls by more than normal noise.
5. Move SQLite to Postgres and Streamlit to a hosted app if more than a few users need it.
