"""Tables written by the LLM layer. Created on demand; the scraper's own schema is not touched."""
from __future__ import annotations

import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS review_enrichment (
    review_key          TEXT NOT NULL REFERENCES reviews(review_key),
    prompt_version      TEXT NOT NULL,
    model               TEXT NOT NULL,
    created_at          TEXT NOT NULL,           -- ISO 8601 UTC
    status              TEXT NOT NULL CHECK (status IN ('ok', 'failed')),
    language            TEXT,                    -- ISO 639-1 as detected by the model
    translated_liked    TEXT,                    -- NULL when the text is already English
    translated_disliked TEXT,
    topics_json         TEXT,                    -- JSON list of {topic, polarity, evidence_quote}; topic = topic id
    severity            TEXT CHECK (severity IN ('none', 'low', 'medium', 'high')),
    safety_flag         INTEGER,                 -- 0/1
    safety_reason       TEXT,
    raw_json            TEXT,                    -- the validated model output, for audit
    error               TEXT,                    -- why a failed row failed
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    PRIMARY KEY (review_key, prompt_version)
);
CREATE INDEX IF NOT EXISTS ix_enrichment_status ON review_enrichment (prompt_version, status);

CREATE TABLE IF NOT EXISTS weekly_summary (
    week_start      TEXT NOT NULL,               -- Monday, YYYY-MM-DD
    facts_hash      TEXT NOT NULL,               -- sha256 of the WeeklyFacts JSON the text was written from
    prompt_version  TEXT NOT NULL,
    source          TEXT NOT NULL CHECK (source IN ('llm', 'template')),
    text_json       TEXT NOT NULL,               -- JSON list of {text, review_keys}
    model           TEXT,
    generated_at    TEXT NOT NULL,
    PRIMARY KEY (week_start, facts_hash, prompt_version)
);
"""


def ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(SCHEMA)
