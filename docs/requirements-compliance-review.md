# Requirements compliance review (independent, skeptical)

Reviewer stance: hiring manager checking the submission against the original brief, verifying rather than trusting
`README.md` and `docs/requirements-traceability.md`. Review date 2026-11-27 (system date). Nothing here touched the
network, wrote to `data/*.db`, or changed code.

**What I actually ran or read**

- `data/reviews.db` read-only (`sqlite3 "file:...?mode=ro"`): per-hotel counts and dates, `scrape_runs`, `review_topics`,
  duplicates, language mix, rating-only share, tag samples.
- A copy of the live DB in my scratch dir, driven through Streamlit `AppTest` (default view, "This week so far",
  "Last 12 weeks" with a hotel subset, topic filter and "Only negative reviews"). Rendered text read back.
- `data/sample_reviews.csv` (parsed), `git ls-files`, `git log -p --all` (secrets, absolute paths, author data).
- `.venv/bin/python -m pytest -q -p no:cacheprovider tests/test_*.py`: **941 passed, 1 xpassed** (matches the "about 940" claim).
- `python -m scraper.run --help` and `python -m insights.pipeline --help` (match the README flags).
- Source: `scraper/{collector,run,browser}.py`, `insights/metrics.py`, `dashboard/app.py`, `dashboard/ui/sections.py`, `dashboard/ui/data.py`.

---

## (a) Verdict summary table

Verdict key: Met / Partly / Not met / Over-claimed in docs. Effort S (under 1 h), M (half a day), L (a day or more).

### 1. Review collection

| Requirement | Verdict | Evidence I gathered | Gap and suggested fix | Effort |
|---|---|---|---|---|
| Collect reviews for the four properties | **Partly** (3 of 4) | DB: Darling Harbour 2,010 (2025-01-31 to 2026-11-27), Olympic 133 (2026-07-06 to 2026-11-27), Potts Point 1,440 (2023-11-28 to 2026-11-27), **Central Sydney 0**. Ledger row 5: `venus-surry-hills` `blocked`, 32 s, "Bot check did not clear". `quarantine` empty; 0 reviews `missing_since`. | The brief names four hotels; one has nothing and two are partial. Re-run Central Sydney alone on an idle connection (command is in ADR 004) and record the attempt. See gap 1. | S to M (human) |
| Reliable alternative to an API | **Partly** | Playwright reads the page's own `ReviewList` responses (`scraper/browser.py`). Works on 3 hotels on one day. Needs a **visible** window (README admits headless gets HTTP 400). `browser.py` has no unit tests by its own admission ("manual smoke test"). | Method is sound and honestly bounded, but "reliable" is demonstrated on one afternoon: 6 ledger runs, 1 failed (DOM race, row 1), 1 blocked (row 5). Cannot run unattended on a server. Recommendation to move to Extranet export is correct and unbuilt. | L (to remove the headful limit) |
| Collect text, rating, date, property, other info | **Met** | Schema has rating, date, title, liked, disliked, language, country, traveller type, room type, nights, stay dates, host reply, helpful votes. 1,146 of 3,583 rows carry a host reply. Reviewer names deliberately dropped. | None material. The sample CSV omits language, nights, stay dates, helpful votes and the review ID. | S |
| Avoid duplicate reviews | **Met** (and better evidenced than the docs say) | `review_key` is Booking's `reviewUrl`, PRIMARY KEY; 3,583 rows = 3,583 distinct keys. Test `test_saving_the_same_reviews_twice_creates_no_duplicates` (`tests/test_store.py`) exists. **Ledger row 3 is a live repeat full run on Olympic: 14 pages, new=0, updated=0**, directly after row 2 (133 new). README says "a live repeat run is not recorded"; it is, in `scrape_runs`. **No content-level dedup:** 17 reviews at Potts Point (1/10, 25 to 28 Oct 2024) have distinct keys and identical text ("I strongly advise against booking this hostel..."), plus 8 other identical-text pairs (query found 10 identical-text groups in total), some cross-hotel. | ID-level dedup is solid. There is no near-duplicate or spam flag, so a campaign of identical reviews counts as 17 separate complaints in All-time views. Add a content fingerprint and a "possible duplicate or campaign" flag. Cite ledger row 3 in the README. | S |
| Support updating with new reviews | **Partly** | `--mode incremental` stops at the first page with `new == 0` (`collector.py`); tests `test_incremental_run_stops_at_first_page_with_nothing_new` and the empty-DB variant exist. **Never run live**: all 6 ledger rows are `full`. The pipeline tags only new or changed reviews (`review_topics_state`). Nothing schedules itself, and a visible browser is needed, so a cron job needs a logged-in desktop session. README claim "Usually 1 page per hotel (about 20 to 30 s each)" is an estimate, not an observation. | Run `python -m scraper.run --property all --mode incremental` once for real and keep the ledger rows. Also: incremental never back-fills the oldest missing reviews of Potts Point or Darling Harbour. | S (human) |
| Handle page changes | **Met** (offline only) | `ParseError("layout probably changed")`; order guard; drift check; end-of-list guard. Tests exist and I located them: `test_changed_layout_raises_parse_error` (test_parse), `test_canary_flags_drift_when_we_collected_far_fewer_than_booking_reports` (test_collector). Drift check did fire live (Potts, Darling `DRIFT`). | The browser selectors (`READ_ALL`, `SORTER`, `NEXT_PAGE`) are untested against any changed layout, and `browser.py` is outside the test suite. Fails loudly, does not self-heal. Drift check is skipped under the default 365-day window. | M |
| Handle errors and temporary failures | **Partly** | Mechanisms and tests: blocked recorded not raised (`test_blocked_run_is_recorded_not_raised_and_keeps_earlier_pages`); one 3 to 4.5 min back-off retry (`test_a_blocked_hotel_is_retried_once_after_a_long_back_off`, test_run_cli); vanished "Next page" waited for 3 times (`test_a_button_that_vanishes_midway_is_waited_for_and_found_again`, test_walk_pages); stale `running` rows closed; Ctrl+C recorded; bad review quarantined (`test_bad_review_is_quarantined_and_others_survive`); reviews panel opened up to 3 times (live evidence: ledger row 1 failed with "Element is not attached to the DOM", row 2 succeeded after the fix). | No per-request retry or backoff: one 30 s timeout on any "Next page" ends the hotel's whole run (`browser.py` catches `PlaywrightTimeout` and raises `FetchError`). The blocked-retry has never fired successfully in reality. | M |
| Document approach, limitations, reliability | **Met** (some over-claims, see (b)) | README "Review collection", "Reliability" table, "Known limitations", ADR 001 to 004, `docs/security/*`. Terms-of-service risk stated plainly. | Fix the specific sentences in (b). | S |

### 2. Operations dashboard

| Requirement | Verdict | Evidence I gathered | Gap and suggested fix | Effort S/M/L |
|---|---|---|---|---|
| Average rating for the **current** week | **Partly, with a labelling problem** | Default "Time period" = "Latest full week". On 27 Nov (Fri) the page showed "Week of Mon 16 Nov to Sun 22 Nov 2026", "Guest score this week 5.0 from 23 reviews", insight "Average rating this week was 5.0 from 23 reviews". The current week (23 to 29 Nov) already has **16 reviews** and is reachable only via the "This week so far" preset (6.6). The cards and insights say "this week" while showing last week; only a small caption has the dates. See bug 1 for a second problem with "latest full week" on Mondays. | Relabel to "Last full week (16 to 22 Nov)" or show both tiles: "Week so far" and "Last full week". Pass wall-clock `today` into `latest_complete_week`. | S |
| Comparison against previous week | **Met** (partial-week caveat) | Default: 5.0 vs 6.4, "Down 1.4 points", counts 23 vs 16, low-sample badge under 5 reviews. "This week so far": 6.6 (16 reviews, Mon to Fri) vs 5.0 (23, full week) labelled **"Good news ... up 1.5"**. | A 5-day partial week is compared with a 7-day week with no like-for-like warning, and the review count (16 vs 23) reads as a drop. Compare the same weekdays or add "week not finished" next to the delta. | S |
| Property-by-property breakdown | **Met** | AppTest default: Olympic 5.3 (11 vs 9 reviews, down 0.8), Potts Point 4.2 (4 vs 1, "Small sample"), Central Sydney "No data" card with reason, Darling Harbour 5.1 (down 2.7). Per-hotel top complaint with "X of Y negative reviews with a comment". Central Sydney is excluded from every number and said so ("Based on 3 of 4 hotels"). | The weekly trend charts are **combined across selected hotels**: there is no per-hotel trend line. A manager has to flip the hotel filter one at a time to see a hotel's trend. | M |
| Review feed (browse and read) | **Met** | 10 per page with Previous/Next, newest or lowest first, topic chips with the evidence sentence, hotel-reply badge, "No reply yet", rating-only compact cards, CSV download (placed under Data health, far from the feed). Foreign-language reviews shown untranslated. | No translation, no per-review "mark as handled" state (read-only). Move the CSV button next to the feed. | S |
| Date and property filters | **Met** | Exact controls: sidebar "Hotels" multiselect (4 names, Central Sydney included though empty); "Time period" select (Latest full week, This week so far, Last week, Last 4 weeks, Last 12 weeks, All time, Custom dates) plus a date-range picker for Custom; feed-only: Topic (complaint/praise x 8), "Only negative reviews", "No reply yet", "Has written comment", free-text search, Sort. I ran "Last 12 weeks" + Darling Harbour and Potts Point + Complaint: Cleanliness + Only negative: "14 reviews match", no exception. | Feed date filter is the global one; there is no feed-local date picker. Acceptable. | S |
| Positive and negative review trends | **Met** | Two charts: (1) average score per week (line) with review-count bars and a "Positive from 8" line; (2) stacked bars of positive, mixed, negative review counts per week, with colour **and** pattern encoding. Bands: 8 and above, 5 to under 8, under 5. Shows at least 8 weeks. | "Negative" is by score only, so a 5 to 7 review with a serious complaint is "mixed" (250 mixed-score reviews carry a negative topic tag, versus 330 sub-5 reviews). Documented in `docs/assumptions.md`. Aggregated, not per hotel. | M |
| Easy for non-technical staff | **Partly** | Plain English, a "How to read this" box, freshness and coverage banners, friendly empty/missing/corrupt-DB states (tested). **Never exercised in a real browser by anyone in the record**: only `AppTest` and an HTTP 200 on `/`. Phone width and CSV download untested (README says so). No user test. No login. | A 10-minute walkthrough with one real ops person, plus a Playwright screenshot pass (the lead is writing e2e tests). | S |

### 3. Review insights

| Requirement | Verdict | Evidence I gathered | Gap and suggested fix | Effort |
|---|---|---|---|---|
| Group reviews into common operational topics | **Met** | All 8 topics present. Tag counts (negative / positive): cleanliness 344 / 473; check_in 150 / 115; staff 186 / 587; noise 139 / 79; facilities 366 / 468; location 56 / 769; room_condition 325 / 435; value 86 / 230. 1,796 of 3,583 reviews carry at least one tag; 4,808 tags in total. | Thin for weekly use: location and value complaints are 56 and 86 across ~3 years, so a weekly "X% mention location" is almost always 0 or 1 review. Value for money is under-detected relative to how often guests mention price. | M |
| Example insight "40% of negative reviews this week mentioned cleanliness" | **Met** | Real generated sentence from the live data (default view): "**50% of negative reviews with a written comment this week mentioned cleanliness (3 of 6; 4 other negative reviews had no comment), down from 75% last week (3 of 4). Last week had only 4 negative reviews with a written comment, so treat the comparison with caution.**" Same shape as the brief, with counts and caveats. | The denominator is chosen (written comments only): the brief-style naive figure would be 3 of 10 = 30%, so the headline percentage is flattered by a factor of 1.7. This is disclosed on screen. "Negative" also excludes mixed-score complaints. And 6 reviews is too few to state a percentage; the sentence says so. | S |
| Methodology and limitations explained | **Met** (one false claim) | README "Insights", `docs/evaluation.md`, in-app "Topics" box. Keywords per sentence, negation, polarity from the liked/disliked box, evidence sentence stored per tag. | The README says non-English reviews "get no topic tags and the dashboard says how many were not analysed". Both halves are false (see (b)). | S |
| Accuracy of insights | **Partly** | Gold file `tests/fixtures/real_gold_labels.json` (100 reviews), **AI annotator, not a human**; held-out 50: P 0.84 R 0.76 F1 0.80; room_condition F1 0.65, check_in recall 0.67. The earlier self-labelled F1 0.95 is correctly disclosed as optimistic. My own sampling of live tags: sub-5 English reviews with text left untagged: 25 of 306 (typos such as "stoff", indirect check-in complaints missed); mixed bag of correct evidence sentences. The classifier has **no language gate**: 47 of 185 French, 19 of 115 Spanish, 23 of 110 German reviews with text carry tags (loan words such as "dinner", "wifi", "reception"), some plainly wrong (French cleanliness complaint "La proprete... pas nettoye correctement" tagged `noise` negative; French kitchen-rot complaint tagged `location` negative). Non-English text is **~29% of reviews with text** (758 of 2,603, excluding `xu` which is English-like); 236 of 542 sub-5 reviews with text (44%) are not English. | The headline "X% of negative reviews" silently has a denominator in which ~44% of reviews cannot be tagged properly, and the dashboard does not tell the user (the `n_non_english` field is computed in `metrics.py` and never rendered). Fix: gate or flag by language, display "N of M not analysed", and add an LLM tier for non-English. Do the 15-minute human spot-check. | M |
| Useful to operations | **Partly** | Extra insights: week-on-week score change, hotel movers, topic spikes, unreplied negatives. Unreplied-negatives alert reads "**432 negative reviews have no hotel reply yet (10 of them from this week). Darling Harbour has the most (273)**" at the top as "Needs attention". | The 432 is an all-time backlog (reviews back to 2025 for Darling Harbour) and is not actionable as a headline. Scope it to the last 30 or 60 days. No alerting, no digest, no assignment. | M |

### 4. Deliverables

| Deliverable | Verdict | Evidence I gathered | Gap and suggested fix | Effort |
|---|---|---|---|---|
| GitHub repo or ZIP with complete source | **Met** (local git only) | 14 commits, 1 author, clean `git status`, 4.3k lines of source, 941 tests. No remote exists in the record. `scripts/spike_*.py` (7 files) are throwaway clutter in the repo. | Push to GitHub or zip it. Move or delete `spike_*`. | S |
| README: setup and install | **Met** | Clear, with the project-root and Python 3.13+ caveats, Windows note, demo-data path with no network. `--help` flags match. The clean-copy install test was done by a prior agent; I did not repeat it. | Pins (`pandas==3.1.1`, `streamlit==1.67.0`, `playwright==1.65.2`) were audited on Python 3.15 only; a reviewer on 3.12 may fail to resolve them. | S |
| README: how to run scraper and frontend | **Met** | Quick start plus "Keeping it up to date" table. | The daily/weekly cadence has never been exercised live. | S |
| README: architecture overview | **Met** | Pipeline diagram, folder table, design choices, all named files exist. | None. | -- |
| README: explanation of collection method | **Met** | "What we found / Method" plus ADR 001 match `browser.py`. | None. | -- |
| README: known limitations and assumptions | **Met** | Prominent, honest "Read this first" at the top; a limitations list; `docs/assumptions.md`. | See (b) for sentences to correct. | S |
| Working local application | **Met** | AppTest on the live DB: no exception, every section renders. `make_demo_db.py` gives a no-network path. | Not seen in a real browser by anyone on record. | S |
| Publicly accessible demo | **Not met** | Nothing deployed. `data/sample/reviews_sample.db` is git-ignored so a Streamlit Cloud deploy from the repo as committed would show "No review data found". `docs/deploy.md` is a recipe, with its host steps marked "[not verified]". | Either deploy (needs a human GitHub and Streamlit account, plus `git add -f` of the sample DB after the privacy checklist) or state clearly that local run is the deliverable. The brief allows "working local application **or** public demo", so this is not a hard failure. | S (human) |
| Sample review data from the listed properties | **Partly** | `data/sample_reviews.csv`, committed: 733 rows. Olympic 133 (2026-07-06 to 2026-11-27), Potts Point 300 (from 2025-06-04), Darling Harbour 300 (from 2026-03-12). **Central Sydney: none.** No emails or phone numbers found by regex. 209 rows have a host reply. | 3 of 4 hotels, and only the newest 300 from two of them. Also note this republishes ~600 verbatim Booking.com review texts in a public repo (terms-of-service and privacy judgment for the owner). Add a language column and the review ID. | S |
| No secrets, cookies or personal data | **Met** | `git grep` and `git log -p --all`: no keys, tokens, cookies, `.env`, DB files or absolute paths in tracked content (hits were test fixtures and prose). `.env.example` holds only a comment. Commit authorship was rewritten to the personal GitHub no-reply address before publishing. Reviewer names never stored. | Staff first names can appear in committed review text (docs admit it). | S |

### 5. Evaluation criteria (verdicts; scores in (d))

| Criterion | Verdict | Evidence | Gap | Effort |
|---|---|---|---|---|
| Reliability of collection | **Partly** | 3 of 4 hotels, 2 partial, incremental never live, one afternoon of runs, headful-only, no per-request retry. Good detection (drift, ledger, order guard). | Gaps 1 to 3 below. | M |
| Code quality and structure | **Met** | Separated parse, fetch, store, collect, classify, metrics, UI; pure-function parser; one definition per concept; contracts doc; 941 tests. | `browser.py` and the Streamlit render paths are the least-tested parts; `metrics.py` is 688 lines; spike scripts. | S |
| Accuracy and usefulness of insights | **Partly** | See section 3. | Gap 5 and 7. | M |
| Dashboard usability for non-technical users | **Partly** | See section 2. | Labels ("this week"), no per-hotel trend, no user test. | S |
| Error handling and data quality controls | **Met** | Quarantine, validation, cross-hotel ID collision refusal, stale-run closing, coverage fields, freshness warnings, security red-team. | No near-duplicate/spam control; no language gate. | S |
| Documentation and ease of setup | **Met** | README is thorough, mostly accurate. | 4 to 5 over-claims, README is 340 lines (long for staff, fine for engineers). | S |
| Product thinking | **Partly** | See (d). | No alert, digest or reply workflow built. | M |

---

## Bugs found (not fixed)

**Bug 1. "Latest full week" skips a week on Monday mornings (headline use case).**
`dashboard/app.py:93` calls `m.latest_complete_week(df_all)` without `today`, so "elapsed" is judged against the newest
review date, not the clock. `insights/metrics.py:62-64` treats a week as complete only if its Sunday is strictly before
that date. Reproduction (no network, no DB writes):

```
.venv/bin/python - <<'E'
import pandas as pd; from datetime import date; from insights import metrics as m
df = pd.DataFrame({"review_date": pd.to_datetime(["2026-11-17","2026-11-24","2026-11-29"]), "rating":[5,6,7]})
print(m.latest_complete_week(df))                        # 2026-11-16  (wrong: week of 23 Nov is finished)
print(m.latest_complete_week(df, today=date(2026,11,30)))# 2026-11-23  (right)
E
```

Effect: on a Monday (30 Nov) where the newest collected review is dated Sunday 29 Nov, the default view shows the week
of 16 to 22 Nov, i.e. a week stale, exactly when "Monday-morning review" is meant to happen. The unit test
`test_latest_complete_week_newest_review_on_sunday_is_not_yet_complete` codifies this behaviour, so it was a deliberate
"no wall clock" choice that does not fit the use. Fix: pass `today=D.sydney_today()`.

**Bug 2. Wrong "this week" labels and non-like-for-like comparison** (documented in the table above, reproducible with
the Time period selector: default view versus "This week so far").

**Observation (possible data bug, not proven).** Potts Point has **0 of 1,440** rating-only reviews, while Darling
Harbour has 921 of 2,010 (46%) and Olympic 59 of 133 (44%). Potts 2026 volume is 122 reviews versus Darling Harbour
485, with a mean score falling from 8.3 (2023) to 4.6 (2026). This pattern suggests the Potts list may be showing a
text-only or otherwise filtered set, in which case the "partial: oldest 946 missing" explanation and the Potts weekly
counts and averages (1 to 4 reviews per week) are not comparable with the other hotels. Not investigated anywhere in
the docs. Needs a human to compare against the live Booking page.

---

## (b) Places where the docs over-claim, under-claim or contradict the code and data

| # | Quote | File | What the code or data shows |
|---|---|---|---|
| 1 | "They get no topic tags and the dashboard says how many were not analysed." | `README.md`, Insights > Known weaknesses | **False on both counts.** The classifier has no language gate: 47 of 185 French, 19 of 115 Spanish, 23 of 110 German reviews with text have tags (some wrong). `CommentCounts.n_non_english` exists in `insights/metrics.py` and no dashboard code reads it (grep). Only a generic "may get fewer topic tags" sentence exists in the "How to read this" box. |
| 2 | "how each hotel scored this week, what changed since last week" | `README.md`, opening paragraph | The default shows the last **complete** week (16 to 22 Nov on 27 Nov); the cards say "this week". |
| 3 | "Reasonable for Monday morning use but different from a literal reading." | `docs/requirements-traceability.md`, "Average rating for the current week" | Not reasonable on all Mondays (bug 1), and the mislabelled "this week" cards are not mentioned. |
| 4 | "Usually 1 page per hotel (about 20 to 30 s each)." | `README.md`, Keeping it up to date | Incremental mode has never been run live (ledger: 6 rows, all `full`). Estimate only. |
| 5 | "a live repeat run is not recorded in this repository" | `README.md`, reliability table; `docs/requirements-traceability.md` | Under-claim. `scrape_runs` row 3 is a live repeat on Olympic (14 pages, 0 new, 0 updated). It is in the git-ignored DB, so it is not in the repo, but the evidence exists and should be quoted. |
| 6 | "Most likely explanation is that Booking.com's bot protection slowed or refused a connection that had just made a large number of requests" ; "The facts that fit this: both failures came straight after long runs" | `docs/adr/004-central-sydney-not-collected.md` | The ledger weakens it: Central Sydney failed 32 s after the Potts crawl ended (15:11:25), but **Darling Harbour started 0.2 s later (15:11:58) on the same connection and collected 201 pages for 14 min without a block**. A Central-specific cause (page variant, longer-than-30 s WAF challenge) is at least as likely. The pause-and-retry safeguards were built on the throttling hypothesis. |
| 7 | "Both collection attempts were blocked" / "blocked twice" | `README.md`, ADR 004 | The ledger holds one blocked row (ADR 004 itself says so); the first attempt is in earlier, unrecorded runs. Unverifiable from the repo. |
| 8 | "Recent weeks, which are what the dashboard is for, are covered for the three collected hotels." | `README.md`, top | Not established for Potts Point (see data observation above); the weekly volume and 0% rating-only anomaly is unexplained. |
| 9 | "Central Sydney ... 2,445 (seen when the page was opened alone)" | `README.md`, What was collected | No ledger row, fixture or screenshot supports the number; it comes from the owner's account. Reasonable, unverifiable. |
| 10 | "Dashboard usability: Observed demo run" / "Working local app ... Headless start gave HTTP 200" | `docs/requirements-traceability.md` | "Observed" means `AppTest` text output and an HTTP status. No one looked at a rendered page. |
| 11 | xfail reason: "OPEN HAND-OFF: .gitignore ... does not ignore data/reviews.db" | `tests/test_security_scraper.py:1265` | Stale: `.gitignore` now ignores it (the test xpasses). Harmless but a stale note in a test file. |
| 12 | "All eight topics present" (traceability, met) | `docs/requirements-traceability.md` | True, but location-negative (56) and value-negative (86) over 3 years are too thin to support weekly percentages; traceability does not say so. |

---

## (c) Ten highest-impact gaps, ranked

| # | Gap | Concrete fix | Who | Effort |
|---|---|---|---|---|
| 1 | **Central Sydney has zero reviews**; one of four required properties, and the sample CSV, evaluation and dashboard all lack it. | Run `python -m scraper.run --property venus-surry-hills --mode full` alone on a rested connection with a visible window; if blocked again, record that attempt, raise `CHALLENGE_WAIT_S` above 30 s, and try once more. Then `python -m insights.pipeline --db data/reviews.db`, `python scripts/export_sample.py --per-property 300`, update README tables. | Human (needs a screen and Booking.com access) | S to M |
| 2 | **Two of three collected hotels are partial and one looks anomalous**: Potts 1,440 of 2,386 with 0% rating-only reviews; Darling Harbour 2,010 of 4,305. Coverage was back-filled by script, not recorded by the scraper. | Re-run both under current code (`--no-date-window` once) so the ledger records `stop_reason` natively; open the live Potts page and compare its review count by rating-only versus text to decide whether the list is text-filtered; document the answer. | Human | M |
| 3 | **Incremental updating has never run live**; "support updating" is unproven end to end. | Run `--mode incremental` for all hotels twice and keep the ledger rows; replace the "20 to 30 s" estimate with observed numbers; add a one-line scheduler example (launchd/cron) in the README. | Human | S |
| 4 | **Headline KPI is mislabelled and fragile.** "This week" means last week; Monday bug; partial-vs-full-week comparison. | Pass wall-clock `today` into `latest_complete_week`; rename cards to "Last full week (16 to 22 Nov)"; add a "Week so far" tile; flag partial-week comparisons. | Code | S |
| 5 | **Non-English reviews are neither analysed nor disclosed**, and wrongly tagged. ~29% of reviews with text and 44% of negative reviews with text; headline percentages hide it. | Gate the classifier by `language` (skip or mark non-English), render "N of M not analysed" next to every topic percentage, correct the README; later add an LLM tier writing to `review_topics.method`. | Code | S (gate and disclosure), M (LLM tier) |
| 6 | **Accuracy evidence rests on one AI annotator and 50 held-out cases.** The author both tuned the keywords and chose the gold sample from the same DB; the product claim (percent of negative reviews per topic) is not directly evaluated. | Do the 15-minute human spot-check in `docs/spot-check.md`; add 100 more labels stratified by sub-5 scores and non-English; report an error range on the weekly percentages; show confidence caveats under n < 10. | Human + code | S to M |
| 7 | **No public demo URL**; the sample DB the demo needs is git-ignored. | Decide whether to publish (privacy checklist in `docs/deploy.md`), `git add -f data/sample/reviews_sample.db`, deploy and put the URL at the top of the README; otherwise state "local run is the deliverable". | Human | S |
| 8 | **No content-level duplicate or campaign detection**: 17 identical 1/10 reviews (Oct 2024) at Potts Point count as 17 complaints. | Hash normalised text; flag clusters of 3 or more identical reviews per hotel in 7 days; exclude or footnote them in All-time and trend views. | Code | S |
| 9 | **Product loop is not closed**: "Needs attention: 432 negative reviews have no reply" is an all-time backlog; there is no alert, digest or assignment. | Scope the reply queue to the last 30 days, sorted oldest first; add a Monday e-mail or Slack digest from `generate_insights`; add a weekly-score-drop alert (roadmap items 3 and 4). | Code | M |
| 10 | **Collection resilience**: one timeout ends a hotel's run, no per-request backoff, headful-only, `browser.py` untested. | Wrap `advance()` in 2 retries with exponential backoff before raising; add a recorded-HTML or mocked-Playwright smoke test for selector drift; implement the CSV-import fetcher for an Extranet export (already the recommended long-term source). | Code | M to L |

Also worth a quick fix: per-hotel trend lines (M), move CSV button beside the feed (S), delete `scripts/spike_*.py` (S), stale xfail comment (S).

---

## (d) Honest scores out of 10

| Criterion | Score | One-line justification |
|---|---|---|
| Reliability of the collection process | **5** | Strong design and loud failure reporting, but only 3 of 4 hotels, two partial, one anomalous, incremental never run live, headful-only, evidence from a single afternoon. |
| Code quality and project structure | **8.5** | Clean layers, pure parser, one definition per concept, 941 passing tests, security red-team; docked for the untested browser layer and spike-script clutter. |
| Accuracy and usefulness of insights | **6** | Brief-style sentence is generated from real data with counts and caveats, but the accuracy evidence is a 50-case AI-labelled holdout, ~44% of negative commented reviews are non-English and mis-handled, and weekly samples are tiny. |
| Dashboard usability for non-technical users | **7** | Plain English, honest banners, good filters and feed; docked for "this week" labels showing last week, the Monday bug, no per-hotel trend, and no real browser or user testing. |
| Error handling and data quality controls | **8** | Quarantine, drift, coverage ledger, ID-collision refusal, freshness warnings; no content-duplicate or language controls. |
| Documentation and ease of setup | **7.5** | Thorough and unusually candid, with a correct, runnable quick start; docked for a few over-claims (b1, b4, b8), length, and the 3.15-only pin audit. |
| Product thinking and business understanding | **7.5** | Right framing (Monday morning, coverage and freshness, reply gaps, "stop scraping, use the Extranet"); the actionable loop (alerts, digest, scoped reply queue) is roadmap only. |

**Overall: about 7 of 10.** Engineering and honesty are above typical for a trial task; the shortfall is on the data
actually delivered (3 of 4 hotels, partial, unexplained Potts pattern) and on a headline metric that is labelled and
computed loosely. The docs' candour about Central Sydney is a real strength: the README opens with it, the dashboard
shows "No data" instead of inventing numbers, and ADR 004 gives the exact recovery command. It does not remove the
fact that one of the four required properties is missing.

---

## (e) What I could not verify, and why

- **Anything on Booking.com** (rules forbade network): the scraper itself, the real selectors, headless HTTP 400, the
  reported totals 2,386 / 4,305 / 2,445 / 133, whether Potts Point's list is text-only, and why Central Sydney was
  blocked.
- **The "blocked twice" history and ADR 003's first-run table**: the ledger starts at the 27 Nov runs; earlier attempts
  are not in it.
- **Real-browser rendering**: I read `AppTest` output only. Layout, colours, the Plotly charts' visual quality, phone
  width, and the CSV download were not seen. The lead's Playwright tests are the right place for this.
- **Human label quality**: no human has checked `tests/fixtures/real_gold_labels.json`; I judged the classifier from
  about 50 sampled tags and the aggregate counts, not an independent labelling.
- **Clean-copy install and the Python 3.13 claim**: I relied on the prior agent's run (I only ran the test suite and
  `--help` in the existing venv).
- **`pip-audit` result and dependency pins on other Python versions.**
- **Public hosting steps** in `docs/deploy.md` (Streamlit Community Cloud behaviour; the doc itself marks them
  "[not verified]").
- **Whether any later commit rewrote history**: I read the 14-commit local history only; no remote exists.
