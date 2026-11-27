"""Data minimisation: guests sometimes type their own (or someone else's) email address or phone number into a
review. Staff never need it to read a review, and the CSV leaves the building, so both are masked before
anything is shown or exported.

    john.smith@gmail.com  ->  j***@***.com
    0412 345 678          ->  [phone removed]

This is a best-effort filter, not a guarantee: unusual spellings ("john at gmail dot com" written in other
words, digits spelled out) can slip through. Every pattern is length-bounded so hostile input cannot make it slow.
"""
from __future__ import annotations

import re

PHONE_MASK = "[phone removed]"

_EMAIL = re.compile(r"(?<![\w.%+\-])([\w.%+\-]{1,64})@([\w\-]{1,63}(?:\.[\w\-]{1,63}){1,8})")
# "john (at) gmail (dot) com", "john [at] gmail [dot] com", "john AT gmail DOT com"
_EMAIL_WORDS = re.compile(
    r"(?<![\w.%+\-])([\w.%+\-]{1,64})\s{0,3}[\(\[\{<]?\s{0,2}\bat\b\s{0,2}[\)\]\}>]?\s{0,3}"
    r"([\w\-]{1,63})\s{0,3}[\(\[\{<]?\s{0,2}\bdot\b\s{0,2}[\)\]\}>]?\s{0,3}([A-Za-z]{2,10})\b", re.I)
_PHONE = re.compile(r"(?<![\w@.])(?:\+\s?)?\(?\d[\d\s().\-]{6,22}\d(?!\w)")
_DATE_LIKE = re.compile(r"\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/.]\d{1,2}[/.]\d{2,4}|\d{1,2}[:.]\d{2}\s?-\s?\d{1,2}[:.]\d{2}")


def _mask_email(m: re.Match) -> str:
    local, domain = m.group(1), m.group(2)
    return f"{local[0]}***@***.{domain.rsplit('.', 1)[-1]}"


def _mask_email_words(m: re.Match) -> str:
    return f"{m.group(1)[0]}***@***.{m.group(3)}"


def _mask_phone(m: re.Match) -> str:
    raw = m.group(0)
    digits = sum(c.isdigit() for c in raw)
    if not 8 <= digits <= 15 or _DATE_LIKE.search(raw):
        return raw
    return PHONE_MASK


def mask_pii(text):
    """Return `text` with email addresses and phone numbers masked. Non-text values are returned unchanged."""
    if not isinstance(text, str) or not text:
        return text
    if "@" in text:
        text = _EMAIL.sub(_mask_email, text)
    if re.search(r"\bat\b", text, re.I) and re.search(r"\bdot\b", text, re.I):
        text = _EMAIL_WORDS.sub(_mask_email_words, text)
    if sum(c.isdigit() for c in text[:20_000]) >= 8:
        text = _PHONE.sub(_mask_phone, text)
    return text


def looks_like_pii(text: str) -> bool:
    """True if masking would change `text`: used to refuse searches for an email address or phone number."""
    return isinstance(text, str) and mask_pii(text) != text


# Strong language, masked in one-line previews only ("f***"); the expanded review shows the guest's own words.
_PROFANITY = ("fuck", "fucking", "fucked", "fucker", "shit", "shitty", "bullshit", "crap", "crappy", "bitch",
              "bastard", "asshole", "arsehole", "dick", "piss", "pissed", "cunt", "wanker", "bloody", "damn",
              "merde", "putain", "mierda", "joder", "scheisse", "scheiße", "cazzo", "merda", "porra", "caralho")
_PROFANITY_RE = re.compile(r"(?<!\w)(" + "|".join(sorted(map(re.escape, _PROFANITY), key=len, reverse=True)) + r")(?!\w)",
                           re.IGNORECASE)


def mask_profanity(text):
    """'This shitty place' -> 'This s***** place'. Whole words only, case-insensitive."""
    if not isinstance(text, str):
        return text
    return _PROFANITY_RE.sub(lambda m: m.group(0)[0] + "*" * (len(m.group(0)) - 1), text)
