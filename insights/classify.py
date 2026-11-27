"""Keyword topic classifier: sentence level, polarity comes from which Booking.com box the text was in."""
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Protocol

from insights.lexicons import LEXICONS, Lexicon
from insights.topics import (
    COMPLAINT_ONLY,
    PROBLEM_KEYWORDS,
    SAFE_PHRASES,
    SAFETY_KEYWORDS,
    TOPICS,
)

METHOD = "keywords"

# Hostile or accidental giant text: only the start of each text is read, and evidence stays short.
MAX_TEXT_CHARS = 5_000
MAX_EVIDENCE_CHARS = 300
# Bump when the way text is cleaned or matched changes, so the pipeline re-tags reviews it already did.
CLASSIFIER_REVISION = "5"   # 4: non-English got no tags; 5: FR/ES/DE/IT/PT lexicons, safety, empty answers

# Characters with no visible width, soft hyphens, bidi controls, variation selectors, control characters:
# "d<zero-width space>irty" must read as "dirty".
_INVISIBLE = re.compile(
    "[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f\u200b-\u200f\u202a-\u202e\u2060-\u206f"
    "\u3164\ufe00-\ufe0f\ufeff\uffa0\U000e0000-\U000e0fff\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_MARKS_AFTER_ASCII = re.compile("(?<=[A-Za-z])[\u0300-\u036f\u1ab0-\u1aff\u1dc0-\u1dff\u20d0-\u20ff]+")
_WORD = re.compile(r"[^\W_]+")
# Look-alike letters (Cyrillic, Greek, a few Latin extensions) -> the Latin letter they imitate.
_CONFUSABLES = {ord(a): b for a, b in zip(
    "аеорсухіјѕһԁɡкмтԛԝӏ" "АВЕКМНОРСТХУ" "αορνιυκτχ" "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧ" "ᴀᴅᴇɪʟᴏᴜ",
    "aeopcyxijshdgkmtqwl" "ABEKMHOPCTXY" "aopviuktx" "ABEZHIKMNOPTYX" "adeilou")}


def _unmask_lookalikes(match: re.Match) -> str:
    word = match.group(0)
    if word.isascii():
        return word
    if all(ch.isascii() or ord(ch) in _CONFUSABLES for ch in word):
        return word.translate(_CONFUSABLES)   # a word made only of Latin letters and look-alikes of them
    return word


def normalise(text: str) -> str:
    """The text the classifier actually reads: capped, NFKC-folded (full-width letters become ASCII), invisible
    characters removed, accents on Latin letters stripped, look-alike letters mapped to Latin."""
    text = unicodedata.normalize("NFKC", text[:MAX_TEXT_CHARS])
    text = _INVISIBLE.sub("", text)
    if not text.isascii():
        text = _MARKS_AFTER_ASCII.sub("", unicodedata.normalize("NFKD", text))
        text = unicodedata.normalize("NFC", text)
        text = _WORD.sub(_unmask_lookalikes, text)
    return text


@dataclass(frozen=True)
class TopicTag:
    topic: str
    polarity: str  # 'positive' | 'negative'
    evidence: str  # the exact sentence that triggered the tag
    method: str


def _compile(keywords) -> re.Pattern:
    alts = sorted((re.escape(k) for k in keywords), key=len, reverse=True)
    return re.compile(
        r"(?<![\w'])(?P<kw>" + "|".join(alts) + r")(?:s|es|ed|ing)?(?![\w'])", re.IGNORECASE
    )


def _phrases(items) -> re.Pattern | None:
    items = [i for i in items if i]
    if not items:
        return None
    alts = sorted((re.escape(i) for i in items), key=len, reverse=True)
    return re.compile(r"(?<![\w'])(?:" + "|".join(alts) + r")(?![\w'])", re.IGNORECASE)


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
_TOKEN = re.compile(r"[\w']+")
_PUNCT_BREAK = r"[,;:()\u2013\u2014]|\s-\s"

_NEGATORS = frozenset({"not", "no", "never", "without", "nothing", "none", "hardly", "cannot", "nor", "zero"})
# Words allowed between a negator and a PROBLEM keyword: "was not at all dirty", "no real noise".
_FILLERS = frozenset({
    "very", "really", "particularly", "that", "too", "so", "at", "all", "overly", "especially", "quite",
    "entirely", "completely", "extremely", "a", "an", "bit", "the", "was", "were", "is", "are", "be", "been",
    "being", "looked", "seemed", "felt", "smelled", "any", "real", "major", "big", "much", "of", "kind",
    "sort", "actually", "always", "single", "little",
})
_EN_ALL_CLEAR = re.compile(
    r"\b(?:no|not\s+any|without\s+any|zero|nothing)\s+(?:\w+\s+){0,2}?"
    r"(?:issues?|problems?|complaints?|complain\w*|faults?|concerns?|negatives?)\b"
    r"|\bnothing\s+(?:bad|negative|wrong|to\s+(?:complain|dislike|criticise|criticize))"
    r"|\b(?:can't|cannot|couldn't|can\s+not|could\s+not)\s+(?:complain|fault|faulted)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class _Profile:
    """Everything the matcher needs for one language."""
    lang: str
    patterns: dict[str, re.Pattern]
    problems: frozenset[str]
    negators: frozenset[str]
    fillers: frozenset[str]
    clause_break: re.Pattern
    all_clear: re.Pattern | None
    safe_phrases: re.Pattern | None = None
    rewrites: tuple[tuple[re.Pattern, str], ...] = ()
    safety_words: frozenset[str] = field(default_factory=frozenset)
    complaint_only: frozenset[str] = frozenset()


def _clause_regex(contrast) -> re.Pattern:
    words = "|".join(sorted((re.escape(w) for w in contrast), key=len, reverse=True))
    return re.compile(_PUNCT_BREAK + (r"|\s(?:" + words + r")\s" if words else ""), re.IGNORECASE)


def _foreign(lang: str, lex: Lexicon) -> _Profile:
    keywords = {tid: tuple(lex.keywords.get(tid, ())) + tuple(lex.loanwords.get(tid, ())) for tid in TOPICS}
    return _Profile(
        lang=lang,
        patterns={tid: _compile(kws) for tid, kws in keywords.items() if kws},
        problems=lex.problems,
        negators=lex.negators,
        fillers=lex.fillers,
        clause_break=_clause_regex(lex.contrast),
        all_clear=_phrases(lex.all_clear),
        rewrites=tuple((re.compile(r"(?<![\w'])" + re.escape(a) + r"(?![\w'])", re.IGNORECASE), b)
                       for a, b in lex.rewrites),
        safety_words=frozenset(lex.keywords.get("safety", ())),
    )


_PROFILES: dict[str, _Profile] = {
    "en": _Profile(
        lang="en",
        patterns={tid: _compile(t.keywords) for tid, t in TOPICS.items()},
        problems=PROBLEM_KEYWORDS,
        negators=_NEGATORS,
        fillers=_FILLERS,
        clause_break=_clause_regex(("but", "however", "although", "though", "while", "whereas", "except")),
        all_clear=_EN_ALL_CLEAR,
        safe_phrases=_phrases(SAFE_PHRASES),
        safety_words=SAFETY_KEYWORDS,
        complaint_only=COMPLAINT_ONLY,
    ),
    **{lang: _foreign(lang, lex) for lang, lex in LEXICONS.items()},
}
SUPPORTED_LANGUAGES = tuple(_PROFILES)


# --- answers that say nothing --------------------------------------------------------------------------------------
_LOW_SIGNAL = frozenset({
    "", "nothing", "none", "n a", "na", "nil", "nope", "no", "not applicable", "nothing really", "nothing at all",
    "nothing much", "nothing to dislike", "nothing to complain about", "nothing to complain", "nothing to report",
    "nothing to say", "nothing in particular", "nothing special", "no complaints", "no complaint",
    "no complaints at all", "none really", "none at all", "everything", "all good", "all fine", "nothing bad",
    "nothing negative", "nothing comes to mind", "cant think of anything", "can t think of anything",
    "rien", "rien a signaler", "rien a dire", "rien de particulier", "rien a redire", "aucun", "tout",
    "nada", "nada que decir", "nada que reclamar", "ninguno", "todo",
    "nichts", "nichts zu bemangeln", "nichts auszusetzen", "alles",
    "niente", "nulla", "niente da segnalare", "nulla da segnalare", "tutto",
    "nada a reclamar", "nada a declarar", "nenhum",
})
_NON_WORD = re.compile(r"[^\w]+")


def is_low_signal(text) -> bool:
    """True for answers like "nothing", "n/a", "-", "no complaints", "everything", "rien", "nada": they carry no
    topic. Used by the classifier (no tags) and the dashboard (shows "No comment" instead of quoting them)."""
    if not isinstance(text, str):
        return True
    folded = normalise(text).lower().replace("\u2019", "'").replace("'", " ")
    return " ".join(_NON_WORD.sub(" ", folded).split()) in _LOW_SIGNAL


# A staff noun in a COMPLAINT only counts as a staff complaint when the clause also says something negative.
# "...which I did inform the receptionist about" is a cleanliness complaint that mentions reception, not a staff one.
_STAFF_NOUNS = frozenset({"reception", "receptionist", "receptionists", "staff", "manager", "service",
                          "customer service", "host", "the team", "lovely team"})
_COMPLAINT_CUES = frozenset({
    "slow", "poor", "bad", "terrible", "awful", "horrible", "disgraceful", "disgusting", "abused", "assaulted",
    "shouted", "yelled", "argued", "lazy", "absent", "lacking", "lack", "unavailable", "nobody", "useless",
    "incompetent", "aggressive", "hostile", "threatened", "refused", "refuse", "worst", "disappointing",
    "unacceptable", "inattentive", "unresponsive", "rudely",
})


def _is_negator(token: str, negators: frozenset[str] = _NEGATORS) -> bool:
    return token in negators or token.endswith("n't")


def _has_complaint_cue(clause: str) -> bool:
    tokens = _TOKEN.findall(clause.lower())
    return any(_is_negator(t) or t in _COMPLAINT_CUES for t in tokens)


def _negated(prefix: str, is_problem: bool, profile: _Profile = _PROFILES["en"]) -> bool:
    """Is the keyword that follows `prefix` (same clause) negated?"""
    tokens = [t for tok in _TOKEN.findall(prefix.lower()) for t in tok.split("'") if t] if profile.lang != "en" \
        else _TOKEN.findall(prefix.lower())
    if not is_problem:
        # "not close to the station", "no air conditioning": any negator earlier in the clause counts.
        return any(_is_negator(t, profile.negators) for t in tokens[-6:])
    # Problem words need a tight window so "no cups and cockroaches" still reports the cockroaches.
    for token in reversed(tokens[-4:]):
        if _is_negator(token, profile.negators):
            return True
        if token not in profile.fillers:
            return False
    return False


def _sentences(text: str | None) -> list[str]:
    if not text or not isinstance(text, str):   # NULL, numbers or blobs in a damaged database: nothing to read
        return []
    text = normalise(text)
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _clauses(sentence: str, clause_break: re.Pattern = _PROFILES["en"].clause_break) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in clause_break.finditer(sentence):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(sentence)))
    return spans


def _keep(is_problem: bool, negated: bool, all_clear: bool, polarity: str) -> bool:
    """Does this keyword match yield a tag in a `polarity` section?"""
    if all_clear:  # "no issues with X": good news about X
        return polarity == "positive"
    if not negated:
        return True
    # "not dirty" is good news (kept only in liked); "not clean", "no kettle" are bad news (kept only in disliked)
    return polarity == ("positive" if is_problem else "negative")


def _blank(match: re.Match) -> str:
    return " " * len(match.group(0))      # same length, so evidence positions stay valid


def _tags_for(text: str | None, polarity: str, profile: _Profile = _PROFILES["en"]) -> list[TopicTag]:
    if is_low_signal(text):
        return []
    tags = []
    for sentence in _sentences(text):
        # Straight apostrophes for matching only; the evidence keeps the original text (same length).
        norm = sentence.replace("\u2019", "'")
        if profile.lang != "en":
            norm = norm.replace("'", " ")      # elision: "d'incendie", "l'emplacement" -> separate words
        if profile.safe_phrases is not None:
            norm = profile.safe_phrases.sub(_blank, norm)
        for pattern, replacement in profile.rewrites:
            norm = pattern.sub(lambda m, r=replacement: r.ljust(len(m.group(0)))[: len(m.group(0))], norm)
        for start, end in _clauses(norm, profile.clause_break):
            clause = norm[start:end]
            all_clear = bool(profile.all_clear.search(clause)) if profile.all_clear is not None else False
            for topic_id, pattern in profile.patterns.items():
                if topic_id == "safety" and polarity == "positive":
                    continue  # a safety tag is only ever a complaint
                decisions = []
                for m in pattern.finditer(clause):
                    kw = m.group("kw").lower()
                    if polarity == "positive" and kw in profile.complaint_only:
                        continue
                    if (profile.lang == "en" and topic_id == "staff" and polarity == "negative"
                            and kw in _STAFF_NOUNS and not _has_complaint_cue(clause)):
                        continue  # a bare mention of staff is not a staff complaint
                    is_problem = kw in profile.problems
                    negated = _negated(clause[: m.start()], is_problem, profile)
                    if topic_id == "safety" and (negated or all_clear):
                        continue  # "no bugs" is not a safety problem
                    decisions.append(_keep(is_problem, negated, all_clear, polarity))
                # One negated keyword cancels the topic in this clause ("staff weren't helpful").
                if decisions and all(decisions):
                    tags.append(TopicTag(topic_id, polarity, sentence[:MAX_EVIDENCE_CHARS], METHOD))
    return tags


def classify_review(liked: str | None, disliked: str | None, language: str | None = "en") -> list[TopicTag]:
    """Topic tags for one review. `language` is an analysis language ("en", "fr", "es", "de", "it", "pt"; see
    insights.language.analysis_language). Any other value, or None, means the review is not analysed: no tags."""
    profile = _PROFILES.get(language or "")
    if profile is None:
        return []
    seen: set[tuple[str, str]] = set()
    result = []
    for tag in _tags_for(liked, "positive", profile) + _tags_for(disliked, "negative", profile):
        if (tag.topic, tag.polarity) not in seen:
            seen.add((tag.topic, tag.polarity))
            result.append(tag)
    return result


# --- extension point -----------------------------------------------------------------------------------------------
class TopicClassifier(Protocol):
    """What the pipeline needs from a topic classifier. The keyword classifier below is the only implementation.

    A different classifier (for example a model-based one) can be plugged in by implementing this interface and
    passing it to insights.pipeline.classify_all; it writes its own `method` value into review_topics, so its tags
    can be told apart from keyword tags. No such classifier exists in this project."""

    method: str

    def classify(self, liked: str | None, disliked: str | None, language: str | None) -> list[TopicTag]: ...


class KeywordClassifier:
    method = METHOD

    def classify(self, liked: str | None, disliked: str | None, language: str | None) -> list[TopicTag]:
        return classify_review(liked, disliked, language)
