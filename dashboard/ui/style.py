"""Look and feel: one stylesheet plus tiny HTML helpers.

All text that comes from the database (reviews, replies, error messages) MUST go through `esc()`
before it is placed inside HTML, because the dashboard renders cards with unsafe_allow_html.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

# Design tokens: the one place for colour, type and spacing. One accent (blue); green/amber/red only for sentiment.
TOKENS = {
    "ink": "#13252F", "muted": "#56666E", "paper": "#F5F7F9", "surface": "#FFFFFF", "line": "#DDE3E8",
    "accent": "#1D64B0", "accent_bg": "#EAF1FA",
    "good": "#17784A", "good_bg": "#E6F2EB", "warn": "#8A5300", "warn_bg": "#FFF3DA", "bad": "#B3362C",
    "bad_bg": "#FBE9E6", "mixed": "#D9A027",
    "space": 8,                    # px; every margin and padding is a multiple of this
    "radius": 12,
    "title": 28, "section": 20, "body": 14, "meta": 12,     # px
}
INK, MUTED, PAPER, CARD, LINE = (TOKENS[k] for k in ("ink", "muted", "paper", "surface", "line"))
TEAL = TOKENS["accent"]            # old name kept: charts import it
GOOD, GOOD_BG, WARN, WARN_BG, BAD, BAD_BG = (TOKENS[k] for k in ("good", "good_bg", "warn", "warn_bg", "bad", "bad_bg"))
FONT = "'Inter', system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif"

# All styling lives in styles.css (next to this file); it is read once per process and injected once per page.
CSS_PATH = Path(__file__).with_name("styles.css")
CSS = "<style>\n" + CSS_PATH.read_text(encoding="utf-8") + "\n</style>"


MAX_TEXT_CHARS = 5_000   # one review is never longer than this on screen; a 5 MB review must not become a 5 MB page
# C0/C1 control characters (except tab and newline) and the bidirectional override/isolate controls that
# can make text read in a different order than it is stored ("Trojan Source" style spoofing).
_HIDDEN = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\u202a-\u202e\u2066-\u2069\u200e\u200f\u061c\ufeff]")


def clean_text(value, limit: int = MAX_TEXT_CHARS) -> str:
    """Untrusted text made safe to show: no control or bidi-override characters, at most `limit` characters."""
    if value is None:
        return ""
    text = _HIDDEN.sub("", str(value))
    if len(text) > limit:
        text = text[:limit].rstrip() + " (shortened)"
    return text


def plain_text(value, limit: int = 300) -> str:
    """Untrusted text for tables and captions: control characters gone, angle brackets gone, shortened."""
    from dashboard.ui.privacy import mask_pii
    return mask_pii(clean_text(value, limit)).replace("<", "").replace(">", "")


def esc(value, limit: int = MAX_TEXT_CHARS) -> str:
    """HTML-escape untrusted text for use inside our own HTML.

    Besides `<>&"'` it also neutralises, as character references, everything Markdown could act on
    (`[`, `]`, backtick, `://`) so that hostile text can never become a link or an image (a tracking pixel)
    even if the renderer treated it as Markdown, and `$` (Streamlit may treat it as maths).
    Line breaks are kept. Hidden control characters are dropped and very long text is shortened.
    """
    if value is None:
        return ""
    out = html.escape(clean_text(value, limit), quote=True)
    out = (out.replace("$", "&#36;").replace("[", "&#91;").replace("]", "&#93;").replace("`", "&#96;")
           .replace("://", ":&#47;&#47;"))
    return out.replace("\r\n", "<br>").replace("\n", "<br>").replace("\r", "<br>")


def badge(text: str, kind: str = "neutral", tip: str = "") -> str:
    title = f' title="{esc(tip)}"' if tip else ""
    return f'<span class="az-badge {kind}"{title}>{esc(text)}</span>'


def one_line(markup: str) -> str:
    """Markdown ends an HTML block at a blank line and treats 4-space indents as code: flatten."""
    return " ".join(line.strip() for line in markup.splitlines() if line.strip())
