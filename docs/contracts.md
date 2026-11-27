# Module contracts

Three modules are built in parallel against this file. If you need to change a contract, do not
change it silently: note it in your final report so the integrator can update the other modules.

## Data (already built, do not modify `scraper/`)

SQLite file, default `data/reviews.db`. Schema is in `scraper/store.py`.

`reviews` columns: review_key (PK), property (slug), rating (REAL 1-10), review_date (ISO `YYYY-MM-DD`,
already Sydney local), title, liked, disliked, language, reviewer_country, traveller_type, room_type,
nights, checkin_date, checkout_date, host_reply (NULL = no reply yet), helpful_votes, content_hash,
first_seen, last_seen, missing_since.
Also: `scrape_runs` (property, mode, started_at, finished_at, status ok|blocked|failed|running, pages, new,
updated, rejected, error) and `quarantine`.

Property slugs and display names: `scraper/config.py` (`PROPERTIES`, `BY_SLUG`).

Reviewer names and avatars are never stored. Do not add them.

## Definitions (single source of truth: `docs/assumptions.md`)

- Week = Monday to Sunday, Australia/Sydney. A week is identified by its Monday date (`week_start`).
- Sentiment band from rating: `>= 8` positive, `>= 5 and < 8` mixed, `< 5` negative.
  Defined ONCE, in `insights/metrics.py` as constants `POSITIVE_FROM = 8.0`, `NEGATIVE_BELOW = 5.0`
  and function `sentiment_band(rating) -> "positive" | "mixed" | "negative"`. Everyone else imports it.
- Every percentage shown to a user must travel with its count (`6 of 15`) and a low-sample flag when n < 5
  (`LOW_SAMPLE_BELOW = 5`).

## Topics (fixed IDs, used by all three modules)

Defined in `insights/topics.py` as `TOPICS: dict[str, Topic]` with `Topic(id, label, keywords)`.

| id | label |
|---|---|
| cleanliness | Cleanliness |
| check_in | Check-in experience |
| staff | Staff behaviour |
| noise | Noise |
| facilities | Facilities |
| location | Location |
| room_condition | Room condition |
| value | Value for money |

`TAXONOMY_VERSION = "1"` also lives in `insights/topics.py`. Bump it whenever keywords change.

## Table written by the classifier, read by metrics and dashboard

```sql
CREATE TABLE IF NOT EXISTS review_topics (
    review_key       TEXT NOT NULL,
    topic            TEXT NOT NULL,     -- one of the ids above
    polarity         TEXT NOT NULL CHECK (polarity IN ('positive','negative')),
    evidence         TEXT NOT NULL,     -- the exact sentence that triggered the tag
    method           TEXT NOT NULL,     -- 'keywords' (later maybe 'llm')
    taxonomy_version TEXT NOT NULL,
    PRIMARY KEY (review_key, topic, polarity)
);
```

Polarity rule: a topic found in the `liked` text is `positive`; in the `disliked` text is `negative`
(Booking already separates the two). Negated phrases ("not dirty", "no issues with noise") must not
produce a negative tag.

## `insights/classify.py` and `insights/pipeline.py` (module 1)

```python
@dataclass(frozen=True)
class TopicTag:
    topic: str; polarity: str; evidence: str; method: str

def classify_review(liked: str | None, disliked: str | None) -> list[TopicTag]: ...
def classify_all(db_path: str) -> ClassifyResult:   # idempotent; (re)classifies a review only if it has no
    ...                                             # tags at current TAXONOMY_VERSION or its content changed
# CLI: python -m insights.pipeline --db data/reviews.db
```

## `insights/metrics.py` (module 2): pure functions, no Streamlit, no printing

```python
POSITIVE_FROM, NEGATIVE_BELOW, LOW_SAMPLE_BELOW  # constants
def sentiment_band(rating: float) -> str
def load_reviews(db_path) -> pd.DataFrame     # all reviews; review_date parsed to datetime64; adds columns
                                              # `week_start` (date of Monday), `band`, `has_reply` (bool),
                                              # `property_name` (display name from scraper.config)
def load_topics(db_path) -> pd.DataFrame      # review_topics rows (empty DataFrame with columns if table missing)
def week_start_of(d: date) -> date
def latest_complete_week(df) -> date          # Monday of the most recent full Mon-Sun week in the data
@dataclass WeekSummary: week_start, n, avg_rating (float|None), positive, mixed, negative
def week_summary(df, week_start, properties=None) -> WeekSummary
@dataclass WeekComparison: current: WeekSummary, previous: WeekSummary, delta: float | None
def compare_weeks(df, week_start, properties=None) -> WeekComparison
def property_breakdown(df, week_start) -> pd.DataFrame   # property, property_name, avg_rating, n, prev_avg, prev_n, delta, low_sample
def weekly_trend(df, start, end, properties=None) -> pd.DataFrame  # week_start, n, avg_rating, positive, mixed, negative
def topic_shares(df, topics, start, end, polarity="negative", properties=None) -> pd.DataFrame
        # topic, label, count, n_reviews, share (count / n_reviews of that sentiment band), low_sample
def topic_by_property(df, topics, start, end, polarity="negative") -> pd.DataFrame  # for a heatmap: property_name, topic, label, count
@dataclass Insight: text: str; kind: "alert" | "good" | "info"; property: str | None; n: int
def generate_insights(df, topics, week_start) -> list[Insight]
        # e.g. "40% of negative reviews this week mentioned cleanliness (6 of 15), up from 20% last week."
        # must show the count with every %, and say so when the sample is small. Max ~6 insights, ranked.
def unreplied_reviews(df, properties=None, max_age_days=None) -> pd.DataFrame
def data_health(db_path) -> pd.DataFrame   # property, property_name, stored, last_ok_at, latest_status, latest_error, stale (bool, > 48h)
```

## `dashboard/` (module 3): Streamlit, uses ONLY the functions above plus the DB for the feed

Entry point `dashboard/app.py`, run with `streamlit run dashboard/app.py`.
DB path from env `REVIEWS_DB` (default `data/reviews.db`). If the file name contains `demo`, show a clear
banner: "DEMO DATA: synthetic, not real guest reviews".

## Demo data

`python scripts/make_demo_db.py` writes `data/demo.db` (synthetic, deterministic, ~300 reviews over 12 weeks,
4 properties). Use it for development and tests. Never present it as real.

## Changes since the first version of this contract

Interfaces changed during the page-cap work and the two security reviews (`docs/security/`). Where this list
and the sections above disagree, this list is current.

- `scrape_runs` gained `truncated`, `reported_total`, `max_pages`, `stop_reason` (`last_page`, `no_new_reviews`,
  `page_cap`, `date_window`) and `since_days`. Existing databases are upgraded in place when the store opens.
- `insights.metrics.data_health` returns three more columns: `truncated`, `reported_total`, `coverage_note`
  (plain-English explanation of a page-limit or date-window run; empty when complete).
- `topic_shares` returns `n_band_total` as well; `n_reviews` is the number of reviews in the band that have written
  text for that polarity (rating-only reviews cannot mention a topic). `comment_counts` was added.
- `insights.metrics._read` raises for unreadable or corrupt databases and only treats "no such table/column" as empty.
  The connection is read-only and an authorizer denies everything except reading (no PRAGMA, no ATTACH).
- `weekly_trend` returns at most 520 weeks. Unknown property slugs are shown as sanitised names.
- `review_topics_state.taxonomy_version` holds `"<TAXONOMY_VERSION>+<CLASSIFIER_REVISION>"`; the first pipeline run after
  an upgrade re-tags every review once. `review_topics.taxonomy_version` is still the plain taxonomy version.
  Tag evidence is the normalised sentence, cut to 300 characters; classifier input is limited to 5,000 characters per text.
- `scraper.store.UpsertResult` gained `conflicts`: a review whose key already belongs to another property is refused and
  quarantined, never moved. Store methods raise `StoreError` instead of raw sqlite errors.
- Parsed values are validated and cleaned (control characters, bidi and zero-width characters removed; text bounded;
  dates, ratings and counts range-checked). `host_reply` is NULL when blank after cleaning.
- The dashboard masks e-mail addresses and phone numbers in review text, hover text, error text and the CSV, and caps
  CSV export at 50,000 rows (`feed_to_csv_limited`).
