"""Is a review written in English? One rule, shared by the pipeline and the dashboard counts.

The keyword classifier only understands English, so reviews that are not English get no topic tags, and the
number of such reviews shown to the user is computed with this same function (``insights.pipeline`` skips them,
``insights.metrics.comment_counts`` counts them), so the two numbers always agree.

The rule, ``is_english_like(language, *texts)``:

1. A language code starting with "en" (en, en-GB, en_US, EN) is English. The text is not looked at.
2. A missing or empty code, or one of Booking.com's non-ISO "x?" codes, is judged by the text itself.
   Looking at the live data, ``xu`` is English (also the "translated to English" bucket), ``xt`` is Traditional
   Chinese, ``xb`` is Brazilian Portuguese, ``xa`` and ``xm`` are Spanish, so the code says nothing reliable.
   The text counts as English when at least 90% of its letters are ASCII letters AND it contains at least one
   common English word (the, and, was, is, to, ...). The second test keeps French, Spanish or Portuguese text
   that happens to carry the English words "wifi" or "location" from passing.
3. Any other code (fr, es, zh, de, it, ja, ko, ru, ar, pl, pt, da, no, ...) is NOT English, whatever the text.
4. No text at all and no usable code: not English-like (there is nothing to analyse either way).

Only the first 10,000 characters of each text are read.
Mixed-language text is judged as a whole: mostly English passes, mostly foreign fails.
"""
from __future__ import annotations

import re

_ASCII_SHARE_MIN = 0.9
MAX_CHARS = 10_000     # per text; the pipeline reads no more than this, so both sides judge the same characters
# Common English words that are not everyday words in French, Spanish, Portuguese, Italian or German
# ("in", "a", "i", "die", "he", and loan words such as "staff", "check", "hostel" are left out on purpose:
# they appear in French, Spanish, Portuguese, Italian or German text).
_STOPWORDS = frozenset({
    "the", "and", "was", "were", "is", "are", "to", "of", "with", "very", "this", "that", "for", "but", "not",
    "had", "have", "my", "you", "it", "would", "good", "great", "nice", "clean", "friendly", "helpful",
    "room", "rooms", "bed", "beds", "stay", "stayed", "place", "nothing", "all", "we", "our",
    "shower", "only", "always", "easy", "convenient", "food", "decent", "better", "too",
})
_WORD = re.compile(r"[A-Za-z']+")
_LETTER = re.compile(r"[^\W\d_]")


def _judge_text(texts: tuple) -> bool:
    text = " ".join(t[:MAX_CHARS] for t in texts if isinstance(t, str) and t.strip())
    if not text:
        return False
    letters = _LETTER.findall(text)
    if not letters:
        return False
    ascii_share = sum(1 for ch in letters if ch.isascii()) / len(letters)
    if ascii_share < _ASCII_SHARE_MIN:
        return False
    return any(w.lower() in _STOPWORDS for w in _WORD.findall(text))


def is_english_like(language: str | None, *texts: str | None) -> bool:
    code = language.strip().lower() if isinstance(language, str) else ""
    if code.startswith("en"):
        return True
    if code == "" or code.startswith("x"):
        return _judge_text(texts)
    return False


# Booking.com language codes for the languages the classifier has keywords for. "xa"/"xm" are Spanish and "xb"
# Brazilian Portuguese in the collected data; other "x?" codes are judged by the text (English or nothing).
_CODE_TO_LANG = {"fr": "fr", "es": "es", "xa": "es", "xm": "es", "de": "de", "it": "it", "pt": "pt", "xb": "pt"}


def analysis_language(language: str | None, *texts: str | None) -> str | None:
    """Which keyword lexicon to use for a review: "en", "fr", "es", "de", "it", "pt", or None (not analysed).

    The pipeline tags with it and the dashboard counts the None cases as "not analysed", so both agree."""
    code = language.strip().lower().replace("_", "-") if isinstance(language, str) else ""
    if code.startswith("en"):
        return "en"
    base = code.split("-")[0]
    if base in _CODE_TO_LANG:
        return _CODE_TO_LANG[base]
    if code == "" or code.startswith("x"):
        return "en" if _judge_text(texts) else None
    return None
