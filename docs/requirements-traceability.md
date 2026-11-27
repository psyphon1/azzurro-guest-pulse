# Requirements traceability

Every requirement, deliverable and evaluation criterion from the assignment, mapped to where it is implemented, what
shows it works, and what is still open. Written on 2026-11-27 by reading the code and running things in a fresh clone
of the committed state.

**Status key:** met = implemented and evidenced; partly met = implemented but with a stated gap or not yet shown on
real data; not met = does not exist yet.

**How this was checked**

- Fresh `git clone` (committed files only), new virtual environment, `pip install -r requirements.txt`:
  `python -m pytest -q` gave **885 passed, 1 xpassed in about 35 s** on Python 3.15.2 and 885 passed on 3.13.
  On Python 3.11, 882 passed and 3 failed (all in `tests/test_export_sample.py`; see risk 4).
- Ran `python -m scraper.run --help`, `python -m insights.pipeline --help`, the demo path (`scripts/make_demo_db.py`,
  pipeline on the demo database, 244 reviews, 741 tags, second run classified 0), started `streamlit run dashboard/app.py`
  headlessly (HTTP 200, health `ok`), and ran `streamlit.testing.v1.AppTest` against the demo database and against a
  missing database: no exceptions, "DEMO DATA" banner present, friendly message when the database is absent.
- Re-ran `scripts/evaluate_classifier.py` on `tests/fixtures/real_gold_labels.json`: held-out half precision 0.84,
  recall 0.76, F1 0.80, as quoted in `docs/evaluation.md`.
- Searched the clone for secrets, `.env`, database files and absolute home paths: none tracked (also enforced by
  `test_no_secret_looking_strings_or_absolute_home_paths_in_tracked_files` and
  `test_no_database_env_cookie_or_key_files_are_tracked`).
- **Not done:** no network access to Booking.com was made. Statements about live collection (what was collected, ADR
  numbers, blocking behaviour) come from the repository's own docs, not from re-observation. The contents of
  `data/reviews.db` were deliberately not opened.

## 1. Data collection

| Requirement | Where implemented | Evidence | Status | Gap or note |
|---|---|---|---|---|
| Collect reviews for the 4 properties (Olympic Paddington, Potts Point, Central Sydney, Darling Harbour) | `scraper/config.py` (`PROPERTIES`), `scraper/run.py` (`--property`), `scraper/browser.py` | `test_run_cli.py` (CLI over all hotels with a fake fetcher); ADR 003 records live runs for Potts Point, Central Sydney and Darling Harbour | partly met | Central Sydney has no collected data yet (blocked twice in the first run, ADR 003). Potts Point and Darling Harbour were collected before the date-window and run-ledger changes and need a re-run. |
| No API access (real browser instead) | `scraper/browser.py` (Playwright, reads the page's own `ReviewList` responses); `docs/adr/001-collection-method.md` | Code reading; `test_walk_pages.py` for the paging loop on saved fixtures | met | Needs a visible browser window (headless gets HTTP 400). Stated in README. Cannot be re-verified offline. |
| Review text, rating, date, property and other fields | `scraper/models.py` (`Review`), `scraper/parse.py` | `test_parse.py` (every card parsed, liked and disliked kept apart, dates to Sydney local date, stay and guest details, hotel reply, helpful votes) | met | Fields: id, property, rating, date, title, liked, disliked, language, country, traveller type, room type, nights, stay dates, hotel reply, helpful votes. Reviewer name deliberately not stored. |
| No duplicate reviews | `scraper/store.py` (`upsert_reviews`, review ID as primary key, content hash) | `test_saving_the_same_reviews_twice_creates_no_duplicates`, `test_edited_review_is_updated_not_duplicated_and_keeps_first_seen` | met | A live repeat run is not recorded anywhere in the repo (the README no longer claims it). Cross-hotel ID collisions are refused (`test_security_scraper.py`). |
| Support updating with new reviews | `scraper/collector.py` (`mode="incremental"` stops at the first page with nothing new; `mode="full"`), `python -m scraper.run --mode incremental`, `insights/pipeline.py` (tags only new or changed reviews) | `test_incremental_run_stops_at_first_page_with_nothing_new`, `test_incremental_run_on_empty_database_reads_every_page`, `test_only_new_reviews_are_classified_on_later_runs` | partly met | Incremental mode has never been run live. Nothing schedules itself; README suggests cron or launchd. Incremental runs do not see edits to old reviews. |
| Handle page changes (layout or API drift) | `scraper/parse.py` raises `ParseError("layout probably changed")`; drift check and order guard in `scraper/collector.py`; `scraper/pagination.py` | `test_changed_layout_raises_parse_error`, `test_layout_change_mid_run_is_recorded_as_failed_with_a_clear_message`, `test_canary_flags_drift_when_we_collected_far_fewer_than_booking_reports`, `test_pages_that_are_not_newest_first_fail_loudly_instead_of_corrupting_the_stop_rules` | met | Designed to fail loudly, not to self-heal. The drift check is skipped when the default 365-day window ends the run, so it protects only runs that reach the end of the list (README corrected to say so). |
| Handle errors and temporary failures | `scraper/errors.py`, `scraper/collector.py` (blocked, failed, interrupted recorded, never raised), `scraper/run.py` (pause between hotels, one retry after 3 to 4.5 min), `scraper/browser.py` (reviews panel opened up to 3 times), `scraper/pagination.py` (missing "Next page" button waited for up to 3 times) | `test_blocked_run_is_recorded_not_raised_and_keeps_earlier_pages`, `test_a_blocked_hotel_is_retried_once_after_a_long_back_off`, `test_ctrl_c_marks_the_run_interrupted_and_keeps_saved_pages`, `test_a_crashed_earlier_run_is_closed_when_the_next_run_starts`, `test_a_button_that_vanishes_midway_is_waited_for_and_found_again` | partly met | No exponential backoff per request; a hard failure ends that hotel's run. Real blocking was seen live (Central Sydney, ADR 003) and the mitigation (pauses, retry) has not yet been proven to get Central Sydney through. |
| Document approach, limitations, reliability | `README.md` (Review collection, Reliability table, Known limitations), `docs/adr/001` to `003`, `docs/security/scraper.md` | Read and cross-checked against code; every flag and default in README matches `--help` (200 pages, 365 days, 60 s pause, 10% drift, 48 h staleness) | met | Terms-of-service risk is stated plainly, with Extranet export or channel feed as the recommended replacement. |

## 2. Operations dashboard

| Requirement | Where implemented | Evidence | Status | Gap or note |
|---|---|---|---|---|
| Average rating for the current week | `insights/metrics.py` (`week_summary`, `latest_complete_week`), `dashboard/ui/sections.py` (`render_kpis`) | `tests/test_metrics.py` (95 tests); AppTest on demo data shows no exception | partly met | The default period is "Latest full week" (last complete Monday to Sunday), not the partial current week; "This week so far" is a preset. Reasonable for Monday morning use but different from a literal reading. |
| Comparison with previous week | `metrics.compare_weeks`, `render_kpis`, insight sentence "up 0.5 from 7.2 last week" | Demo output of `generate_insights` (observed) and `test_metrics.py` | met | Counts shown beside every comparison; "small sample" warning under 5 reviews. |
| Property-by-property breakdown | `metrics.property_breakdown`, `sections.render_properties` | Observed columns: score, n, previous score, delta, low-sample flag; `test_runs_on_demo_data_without_exception` | met | Central Sydney will show empty until it is collected. |
| Review feed | `sections.render_feed` | `test_feed_filters_and_pagination_run`, `test_feed_never_mentions_reviewer_identity`, `test_rating_only_reviews_get_compact_card_and_filter` | met | Also topic, text search, negative only, no reply yet, has comment, sort, CSV export. CSV button not exercised by an automated test (README says so). |
| Date and property filters | `dashboard/app.py` sidebar (Hotels, Time period presets, custom dates) | `test_no_hotel_selected_shows_hint`, `test_empty_range_shows_empty_state` | met | |
| Positive and negative review trends | `metrics.weekly_trend` (positive, mixed, negative counts per week), `sections.render_trends` | Observed columns; `test_metrics.py` | met | Band thresholds (8 and above positive, below 5 negative) are one constant block in `metrics.py`. `docs/assumptions.md` still words "negative" as "rating below 5, or written complaint with a low rating"; the code uses the score only (see risk 5). |
| Usable by non-technical staff | `dashboard/ui/sections.py` (plain-English insights first, "How to read this"), `dashboard/ui/style.py`, `.streamlit/config.toml` | Observed demo run; friendly empty, missing and corrupt-database states (`test_missing_db_shows_message_not_exception`, `test_db_without_tables_shows_message_not_exception`) | partly met | No usability test with a real staff member. Phone-width layout and CSV download not tested. Streamlit emits `use_container_width` deprecation warnings (Streamlit 1.67, pinned) that will matter if the pin is ever lifted. No login (documented). |
| Data freshness and failures visible | `metrics.data_health`, `sections.render_health`, 48 h staleness warning, truncation notice | `test_page_cap_is_explained_in_the_banner_and_health_table`, `test_no_cap_note_when_nothing_was_truncated` | met | Product-thinking extra beyond the brief. |

## 3. Review insights

| Requirement | Where implemented | Evidence | Status | Gap or note |
|---|---|---|---|---|
| Group reviews into the 8 operational topics (cleanliness, check-in, staff behaviour, noise, facilities, location, room condition, value for money) | `insights/topics.py` (taxonomy), `insights/classify.py` (keyword and negation rules, evidence sentence stored), `insights/pipeline.py` (`review_topics`) | `tests/test_classify.py`, `tests/test_pipeline.py`; demo run tagged 244 reviews with 741 tags | met | All eight topics present. Keyword method chosen for cost, determinism and explainability. |
| Accuracy of the topics | `docs/evaluation.md`, `scripts/evaluate_classifier.py`, `tests/fixtures/real_gold_labels.json` | Re-run: held-out half (50 reviews) precision 0.84, recall 0.76, F1 0.80; dev half F1 0.92 (partly memorised); self-labelled set F1 0.95 (optimistic, disclosed) | partly met | Labels come from an AI annotator, not a person; 100 reviews, English only, three hotels (no Central Sydney). Weakest: room condition F1 0.65, check-in recall 0.67. A human spot-check is still needed before quoting the figures. |
| Non-English reviews | Skipped by the classifier; counted and shown on the dashboard | `docs/evaluation.md`, README "Known weaknesses" | partly met | English only: about 20% of real reviews get no topic tags. Rating, date and counts still include them. |
| Example insight such as "40% of negative reviews this week mentioned cleanliness" | `metrics.generate_insights`, `_topic_insight` | Observed on demo data: "67% of negative reviews with a written comment this week mentioned check-in experience (2 of 3)" | met | Percentages always carry counts, and use reviews with written comments as the base (about 4 in 10 real reviews are rating-only). That is more honest than the brief's wording but gives larger percentages than a naive count. |
| Insights useful to operations | `generate_insights` also covers score change, hotel movers, topic spikes and negative reviews with no hotel reply | Observed demo output | met | Not validated with real operations staff. |

## 4. Deliverables

| Requirement | Where implemented | Evidence | Status | Gap or note |
|---|---|---|---|---|
| Complete source code | Whole repository | Fresh clone installs and passes the tests | met | `scripts/spike_*.py` are throwaway investigation scripts kept as a record; they add clutter. |
| README: setup | `README.md` Quick start | Followed literally in a fresh clone; defects found and fixed (Python version claim, missing time estimate, the pipeline line setting an unneeded variable, no note about starting from the project root) | met | Install took about 15 s; Chromium download was cached, so a first-time download was not timed. |
| README: how to run scraper and frontend | `README.md` Quick start and "Keeping it up to date" | `--help` output compared flag by flag with README | met | Real collection not re-run (not allowed here). |
| README: architecture overview | `README.md` Architecture (diagram, folder table, design choices) | All named files exist | met | |
| README: explanation of collection method | `README.md` Review collection; `docs/adr/001-collection-method.md` | Read against `scraper/browser.py` | met | |
| README: known limitations and assumptions | `README.md` Known limitations, Known weaknesses, Assumptions; `docs/assumptions.md` | Read | met | Minor inconsistency in the definition of "negative" (risk 5). |
| Working local app | `dashboard/app.py`, `scripts/make_demo_db.py` | Headless start gave HTTP 200 and health `ok`; AppTest clean on demo data | met | Works on demo data from a fresh clone with no scraping. On real data it needs a successful collection first. |
| Public demo | None | Not deployed | not met | A deployment is in progress separately (`docs/deploy.md`, sample mode). Until a URL exists this stays open. |
| Sample review data from the listed properties | `scripts/export_sample.py` (writes `data/sample_reviews.csv` and `data/sample/reviews_sample.db`) | Script and its tests exist and pass on Python 3.13 and 3.15 | not met | `sample_reviews.csv` has not been generated, and Central Sydney has no data to put in it. The script fails on Python 3.11. The CSV and sample DB are intended to be committed. |
| No secrets committed | `.gitignore` (`.env`, `*.pem`, `cookies*.json`, `data/*.db`), `.env.example` (empty value) | Grep of the clone: no keys, no `.env`, no databases, no `/Users/` or `/home/` paths; two regression tests scan tracked files | met | `.env.example` mentions an `ANTHROPIC_API_KEY` "if you turn on the AI classifier". No such classifier exists (README lists it as roadmap), so the comment is misleading and should be removed or reworded. |

## 5. Evaluation criteria

| Criterion | Where implemented | Evidence | Status | Gap or note |
|---|---|---|---|---|
| Reliability of collection | Collector ledger, stop rules, drift check, retries, throttling pauses, date window, page cap | 885 offline tests; live behaviour documented in ADR 002 and 003 | partly met | Biggest weakness. Only partial live coverage: Central Sydney never collected, two hotels collected under older code, incremental never run live, and the site blocked the scraper during development. |
| Code quality and structure | Separate parse, fetch, store, collect, classify, metrics and UI layers; one definition per concept; `docs/contracts.md` | 885 tests, fresh-clone install clean, tests green on two Python versions | met | Python 3.11 is not supported for the sample export (see risk 4). `scripts/spike_*.py` clutter. |
| Accuracy and usefulness of insights | See section 3 | Held-out F1 0.80 reproduced | partly met | See classifier caveats above. |
| Dashboard usability for non-technical users | See section 2 | Observed demo run, empty and error states tested | partly met | No real user test; layout on phones untested. |
| Error handling and data quality controls | `scraper/models.py` validation, quarantine table, `scraper/store.py`, `docs/security/*.md` | `test_bad_review_is_quarantined_and_others_survive`, about 180 security tests in `test_security_scraper.py` and `test_security_dashboard.py` | met | Stronger than the brief asks for. |
| Documentation and ease of setup | `README.md`, `docs/` | Fresh-clone run; README corrected where it was wrong or vague | met | Setup needs Python 3.13 or newer for every script to work. |
| Product thinking | README "Recommended next step: stop scraping" and Roadmap; freshness and coverage banners; honest limitation statements | Read | met | Roadmap items (Extranet feed, multilingual classifier, digest) are intentions, not built. |

## Top 5 risks to the submission, ranked by impact

1. **The data is incomplete and partly stale.** Central Sydney has no data, and Darling Harbour and Potts Point predate
   the date-window and ledger changes. A reviewer opening the dashboard will see one empty hotel and uncertain coverage.
   Needs live re-runs (a human must do these) before submission, then re-run the pipeline.
2. **No public demo URL and no sample data files.** Two named deliverables are missing: `sample_reviews.csv` has not
   been generated and nothing is deployed. If collection fails again, a reviewer has nothing real to look at except
   synthetic demo data.
3. **Collection reliability is unproven end to end.** Incremental mode has never run live, the block on Central Sydney
   has not been shown to be solved by the new pauses and retry, and the drift check is skipped under the default
   365-day window, so a silently short weekly run may go unflagged. The scraper also needs a visible browser, so it
   cannot run unattended on a server.
4. **FIXED after this review: Python 3.11 broke the sample export.** `scripts/export_sample.py` attaches the live database with a `file:` URI
   through a connection that was not opened with `uri=True`; on 3.11 this raises `OperationalError`, which fails 3 tests.
   Fix: open the destination with `sqlite3.connect(..., uri=True)` (or attach by plain path with a read-only guard).
   README now says to use 3.13 or newer. Any reviewer on an older Python would hit it.
5. **Insight accuracy rests on an AI-labelled, English-only evaluation, and one definition is inconsistent.** F1 0.80
   comes from 50 held-out reviews labelled by an AI annotator; about 20% of real reviews are untagged; room condition
   and check-in are weak. Separately, `docs/assumptions.md` defines "negative" as "rating below 5, or written complaint
   with a low rating" while the code and README use the score alone. Reconcile the wording and get a human spot-check
   of about 50 reviews before quoting accuracy.
