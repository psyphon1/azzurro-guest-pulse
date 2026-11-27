"""Look and feel: one stylesheet plus tiny HTML helpers.

All text that comes from the database (reviews, replies, error messages) MUST go through `esc()`
before it is placed inside HTML, because the dashboard renders cards with unsafe_allow_html.
"""
from __future__ import annotations

import html
import re

# Colours. Good = green, watch = amber, bad = red. Never the only signal: always paired with words/arrows.
INK = "#1B2A2F"
MUTED = "#5B6B70"
PAPER = "#F6F3EC"
CARD = "#FFFFFF"
LINE = "#E2DDD0"
TEAL = "#0F5C66"
GOOD = "#1E7B4F"
GOOD_BG = "#E6F3EB"
WARN = "#9A6200"
WARN_BG = "#FFF3D6"
BAD = "#B3372D"
BAD_BG = "#FBE8E5"

CSS = f"""
<style>
:root {{ color-scheme: light; }}
.stApp {{ background: {PAPER}; color: {INK}; }}
[data-testid="stSidebar"] {{ background: #EDE8DB; }}
.stApp, .stApp p, .stApp label, .stApp li, .stApp span {{ color: {INK}; }}
.block-container {{ padding-top: 1.6rem; max-width: 1180px; }}
h1, h2, h3 {{ font-family: Georgia, 'Iowan Old Style', 'Times New Roman', serif; color: {INK}; letter-spacing: -0.01em; }}
h2 {{ border-bottom: 2px solid {LINE}; padding-bottom: .3rem; margin-top: 1.6rem; }}
.az-sub {{ color: {MUTED}; margin: -0.4rem 0 .8rem 0; font-size: .95rem; }}
.az-banner-demo {{ background: #2B2B2B; color: #FFE08A !important; font-weight: 700; padding: .75rem 1rem;
  border-radius: 8px; border: 3px dashed #FFE08A; margin-bottom: .8rem; letter-spacing: .02em; }}
.az-banner-demo * {{ color: #FFE08A !important; }}
.az-fresh {{ border-radius: 8px; padding: .55rem .9rem; margin-bottom: .8rem; font-size: .92rem;
  border: 1px solid {LINE}; background: {CARD}; }}
.az-fresh.warn {{ background: {WARN_BG}; border-color: #E6C26B; }}
.az-fresh b {{ color: {INK}; }}
.az-card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; padding: .9rem 1rem; height: 100%;
  box-shadow: 0 1px 0 rgba(0,0,0,.03); }}
/* Make cards in one row the same height: Streamlit's column wrappers must pass the height down. */
[data-testid="stHorizontalBlock"] {{ align-items: stretch; }}
[data-testid="stColumn"] > div, [data-testid="stColumn"] [data-testid="stVerticalBlock"],
[data-testid="stColumn"] [data-testid="stElementContainer"], [data-testid="stColumn"] [data-testid="stMarkdown"],
[data-testid="stColumn"] [data-testid="stMarkdown"] > div,
[data-testid="stColumn"] [data-testid="stMarkdownContainer"] {{ height: 100%; }}
.az-label {{ font-size: .78rem; text-transform: uppercase; letter-spacing: .06em; color: {MUTED} !important; font-weight: 600; }}
.az-value {{ font-family: Georgia, serif; font-size: 2.2rem; line-height: 1.15; color: {INK}; margin: .15rem 0; }}
.az-value small {{ font-size: .9rem; color: {MUTED}; font-family: system-ui, sans-serif; }}
.az-note {{ font-size: .85rem; color: {MUTED} !important; }}
.az-up {{ color: {GOOD} !important; font-weight: 700; }}
.az-down {{ color: {BAD} !important; font-weight: 700; }}
.az-flat {{ color: {MUTED} !important; font-weight: 700; }}
.az-badge {{ display: inline-block; font-size: .74rem; font-weight: 700; padding: .12rem .5rem; border-radius: 999px;
  border: 1px solid transparent; margin-right: .3rem; white-space: nowrap; }}
.az-badge.warn {{ background: {WARN_BG}; color: {WARN} !important; border-color: #E6C26B; }}
.az-badge.good {{ background: {GOOD_BG}; color: {GOOD} !important; border-color: #A9D3BC; }}
.az-badge.bad {{ background: {BAD_BG}; color: {BAD} !important; border-color: #E5ADA7; }}
.az-badge.neutral {{ background: #EEF0EE; color: {MUTED} !important; border-color: {LINE}; }}
.az-mix {{ display: flex; height: 12px; border-radius: 6px; overflow: hidden; margin: .5rem 0 .3rem 0; background: #EEE; }}
.az-mix span {{ display: block; height: 100%; }}
.az-insight {{ display: flex; gap: .7rem; align-items: flex-start; background: {CARD}; border: 1px solid {LINE};
  border-left-width: 6px; border-radius: 8px; padding: .65rem .9rem; margin-bottom: .5rem; }}
.az-insight.alert {{ border-left-color: {BAD}; }}
.az-insight.good {{ border-left-color: {GOOD}; }}
.az-insight.info {{ border-left-color: {TEAL}; }}
.az-insight .tag {{ font-size: .72rem; font-weight: 800; text-transform: uppercase; letter-spacing: .05em; white-space: nowrap; padding-top: .15rem; }}
.az-insight.alert .tag {{ color: {BAD} !important; }}
.az-insight.good .tag {{ color: {GOOD} !important; }}
.az-insight.info .tag {{ color: {TEAL} !important; }}
.az-review {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 12px; padding: .9rem 1rem; margin-bottom: .8rem; }}
.az-review .meta {{ font-size: .85rem; color: {MUTED} !important; margin: .15rem 0 .5rem 0; }}
.az-review .head {{ display: flex; flex-wrap: wrap; gap: .5rem; align-items: center; }}
.az-score {{ font-family: Georgia, serif; font-weight: 700; font-size: 1.05rem; padding: .1rem .55rem; border-radius: 8px; }}
.az-score.good {{ background: {GOOD_BG}; color: {GOOD} !important; }}
.az-score.warn {{ background: {WARN_BG}; color: {WARN} !important; }}
.az-score.bad {{ background: {BAD_BG}; color: {BAD} !important; }}
.az-liked {{ border-left: 4px solid {GOOD}; background: {GOOD_BG}; padding: .45rem .7rem; border-radius: 0 8px 8px 0; margin: .35rem 0; }}
.az-disliked {{ border-left: 4px solid {BAD}; background: {BAD_BG}; padding: .45rem .7rem; border-radius: 0 8px 8px 0; margin: .35rem 0; }}
.az-liked .h {{ color: {GOOD} !important; font-weight: 700; font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; }}
.az-disliked .h {{ color: {BAD} !important; font-weight: 700; font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; }}
.az-reply {{ border-left: 4px solid {TEAL}; background: #E8F1F2; padding: .45rem .7rem; border-radius: 0 8px 8px 0; margin: .35rem 0; }}
.az-reply .h {{ color: {TEAL} !important; font-weight: 700; font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; }}
.az-chip {{ display: inline-block; font-size: .78rem; padding: .1rem .55rem; border-radius: 6px; margin: .2rem .3rem 0 0; font-weight: 600; }}
.az-chip.neg {{ background: {BAD_BG}; color: {BAD} !important; border: 1px solid #E5ADA7; }}
.az-chip.pos {{ background: {GOOD_BG}; color: {GOOD} !important; border: 1px solid #A9D3BC; }}
@media (max-width: 640px) {{
  .az-value {{ font-size: 1.8rem; }}
  .az-insight {{ flex-direction: column; gap: .2rem; }}
}}
</style>
"""


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
