"""Keyword topic classifier: sentence level, polarity comes from which Booking.com box the text was in."""
import re
import unicodedata
from dataclasses import dataclass

from insights.topics import PROBLEM_KEYWORDS, TOPICS

METHOD = "keywords"

# Hostile or accidental giant text: only the start of each text is read, and evidence stays short.
MAX_TEXT_CHARS = 5_000
MAX_EVIDENCE_CHARS = 300
# Bump when the way text is cleaned or matched changes, so the pipeline re-tags reviews it already did.
CLASSIFIER_REVISION = "3"

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


_PATTERNS = {tid: _compile(t.keywords) for tid, t in TOPICS.items()}
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
# A clause ends at punctuation or a contrast word; negation never reaches across a clause boundary.
_CLAUSE_BREAK = re.compile(r"[,;:()\u2013\u2014]|\s-\s|\s(?:but|however|although|though|while|whereas|except)\s")
_TOKEN = re.compile(r"[\w']+")

_NEGATORS = frozenset({"not", "no", "never", "without", "nothing", "none", "hardly", "cannot", "nor", "zero"})
# Words allowed between a negator and a PROBLEM keyword: "was not at all dirty", "no real noise".
_FILLERS = frozenset({
    "very", "really", "particularly", "that", "too", "so", "at", "all", "overly", "especially", "quite",
    "entirely", "completely", "extremely", "a", "an", "bit", "the", "was", "were", "is", "are", "be", "been",
    "being", "looked", "seemed", "felt", "smelled", "any", "real", "major", "big", "much", "of", "kind",
    "sort", "actually", "always", "single", "little",
})
_ALL_CLEAR = re.compile(
    r"\b(?:no|not\s+any|without\s+any|zero|nothing)\s+(?:\w+\s+){0,2}?"
    r"(?:issues?|problems?|complaints?|complain\w*|faults?|concerns?|negatives?)\b"
    r"|\bnothing\s+(?:bad|negative|wrong|to\s+(?:complain|dislike|criticise|criticize))"
    r"|\b(?:can't|cannot|couldn't|can\s+not|could\s+not)\s+(?:complain|fault|faulted)\b",
    re.IGNORECASE,
)


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


def _has_complaint_cue(clause: str) -> bool:
    tokens = _TOKEN.findall(clause.lower())
    return any(_is_negator(t) or t in _COMPLAINT_CUES for t in tokens)


def _is_negator(token: str) -> bool:
    return token in _NEGATORS or token.endswith("n't")


def _negated(prefix: str, is_problem: bool) -> bool:
    """Is the keyword that follows `prefix` (same clause) negated?"""
    tokens = _TOKEN.findall(prefix.lower())
    if not is_problem:
        # "not close to the station", "no air conditioning": any negator earlier in the clause counts.
        return any(_is_negator(t) for t in tokens[-6:])
    # Problem words need a tight window so "no cups and cockroaches" still reports the cockroaches.
    for token in reversed(tokens[-4:]):
        if _is_negator(token):
            return True
        if token not in _FILLERS:
            return False
    return False


def _sentences(text: str | None) -> list[str]:
    if not text or not isinstance(text, str):   # NULL, numbers or blobs in a damaged database: nothing to read
        return []
    text = normalise(text)
    return [s.strip() for s in _SENTENCE_SPLIT.split(text) if s.strip()]


def _clauses(sentence: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _CLAUSE_BREAK.finditer(sentence):
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


def _tags_for(text: str | None, polarity: str) -> list[TopicTag]:
    tags = []
    for sentence in _sentences(text):
        # Straight apostrophes for matching only; the evidence keeps the original text (same length).
        norm = sentence.replace("\u2019", "'")
        for start, end in _clauses(norm):
            clause = norm[start:end]
            all_clear = bool(_ALL_CLEAR.search(clause))
            for topic_id, pattern in _PATTERNS.items():
                decisions = []
                for m in pattern.finditer(clause):
                    if (topic_id == "staff" and polarity == "negative" and m.group("kw").lower() in _STAFF_NOUNS
                            and not _has_complaint_cue(clause)):
                        continue  # a bare mention of staff is not a staff complaint
                    is_problem = m.group("kw").lower() in PROBLEM_KEYWORDS
                    negated = _negated(clause[: m.start()], is_problem)
                    decisions.append(_keep(is_problem, negated, all_clear, polarity))
                # One negated keyword cancels the topic in this clause ("staff weren't helpful").
                if decisions and all(decisions):
                    tags.append(TopicTag(topic_id, polarity, sentence[:MAX_EVIDENCE_CHARS], METHOD))
    return tags


def classify_review(liked: str | None, disliked: str | None) -> list[TopicTag]:
    seen: set[tuple[str, str]] = set()
    result = []
    for tag in _tags_for(liked, "positive") + _tags_for(disliked, "negative"):
        if (tag.topic, tag.polarity) not in seen:
            seen.add((tag.topic, tag.polarity))
            result.append(tag)
    return result
