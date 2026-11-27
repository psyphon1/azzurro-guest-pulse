"""Look and feel: one stylesheet plus tiny HTML helpers.

All text that comes from the database (reviews, replies, error messages) MUST go through `esc()`
before it is placed inside HTML, because the dashboard renders cards with unsafe_allow_html.
"""
from __future__ import annotations

import html
import re

# Colours. A cool harbour palette ("azzurro" is azure): white surfaces on a pale blue-grey ground, one azure accent.
# Good = green, watch = amber, bad = red, and never the only signal: always paired with words or arrows.
INK = "#13252F"
MUTED = "#56666E"
PAPER = "#F3F6F8"
CARD = "#FFFFFF"
LINE = "#DCE3E8"
TEAL = "#1C6DB5"          # the azure accent (name kept for the charts that import it)
GOOD = "#17784A"
GOOD_BG = "#E5F2EA"
WARN = "#8F5600"
WARN_BG = "#FFF4DC"
BAD = "#B3362C"
BAD_BG = "#FBE9E6"
FONT = "'Avenir Next', 'Segoe UI Variable Text', 'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif"

CSS = f"""
<style>
:root {{ color-scheme: light; }}
.stApp {{ background: {PAPER}; color: {INK}; }}
/* Never restyle Streamlit's icon spans: they draw their icons from a ligature font, and a text font shows the raw words. */
.stApp, .stApp p, .stApp label, .stApp li, .stApp input, .stApp button, .stApp textarea,
.stApp span:not([data-testid="stIconMaterial"]):not(.material-symbols-rounded) {{ font-family: {FONT}; }}
.stApp, .stApp p, .stApp label, .stApp li, .stApp span {{ color: {INK}; }}
[data-testid="stSidebar"] {{ background: {CARD}; border-right: 1px solid {LINE}; }}
.block-container {{ padding-top: 2rem; max-width: 1120px; }}
h1, h2, h3 {{ font-family: {FONT}; color: {INK}; letter-spacing: -0.015em; }}
h1 {{ font-size: 1.55rem !important; font-weight: 700 !important; padding-bottom: 0 !important; }}
h2 {{ font-size: 1.3rem !important; font-weight: 650 !important; margin-top: 2.4rem !important; padding-bottom: .1rem !important; }}
h3 {{ font-size: 1.05rem !important; font-weight: 650 !important; margin-top: 1.6rem !important; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{ color: {MUTED} !important; font-size: .86rem; opacity: 1 !important; }}
.az-sub {{ color: {MUTED}; margin: .15rem 0 1.4rem 0; font-size: .95rem; }}
.az-banner-demo {{ background: #22313A; color: #FFE08A !important; font-weight: 700; padding: .7rem 1rem;
  border-radius: 6px; border: 2px dashed #FFE08A; margin-bottom: .9rem; }}
.az-banner-demo * {{ color: #FFE08A !important; }}
.az-fresh {{ border-radius: 6px; padding: .6rem .9rem; margin-bottom: .7rem; font-size: .9rem; line-height: 1.5;
  border: 1px solid {LINE}; background: {CARD}; }}
.az-fresh.warn {{ background: {WARN_BG}; border-color: #EBCB82; }}
.az-fresh ul {{ margin: .25rem 0 0 1.1rem; padding: 0; }}
.az-fresh li {{ margin: .1rem 0; }}
.az-fresh b {{ color: {INK}; }}
.az-fresh .more {{ color: {MUTED} !important; }}

/* The week's answer: one big number on Booking.com's 1 to 10 scale. The only loud thing on the page. */
.az-hero {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 10px; padding: 1.3rem 1.5rem 1.1rem; }}
.az-hero .row {{ display: flex; flex-wrap: wrap; align-items: flex-end; gap: .4rem 1.6rem; }}
.az-big {{ font-size: 4.2rem; line-height: .95; font-weight: 700; letter-spacing: -0.04em; font-variant-numeric: tabular-nums; color: {INK}; }}
.az-big small {{ font-size: 1.1rem; font-weight: 500; letter-spacing: 0; color: {MUTED}; }}
.az-hero .verdict {{ font-size: 1.1rem; line-height: 1.45; padding-bottom: .35rem; max-width: 36rem; }}
.az-hero .verdict .az-note {{ display: block; font-size: .88rem; }}
.az-scale {{ position: relative; margin: 1.3rem 0 .2rem; height: 10px; border-radius: 5px;
  background: linear-gradient(90deg, {BAD_BG} 0 44.4%, {WARN_BG} 44.4% 77.8%, {GOOD_BG} 77.8% 100%);
  box-shadow: inset 0 0 0 1px {LINE}; }}
.az-scale .now, .az-scale .was {{ position: absolute; top: 50%; width: 18px; height: 18px; margin: -9px 0 0 -9px; border-radius: 50%; }}
.az-scale .now {{ background: {INK}; box-shadow: 0 0 0 3px {CARD}; z-index: 2; }}
.az-scale .was {{ background: {CARD}; border: 2px dashed {MUTED}; z-index: 1; }}
.az-ticks {{ position: relative; height: 1.2rem; font-size: .76rem; color: {MUTED}; font-variant-numeric: tabular-nums; }}
.az-ticks span {{ position: absolute; transform: translateX(-50%); color: {MUTED} !important; white-space: nowrap; }}
.az-ticks span:first-child {{ transform: none; }}
.az-ticks span:last-child {{ transform: translateX(-100%); }}
.az-key {{ font-size: .82rem; color: {MUTED} !important; margin-top: .1rem; }}
.az-stats {{ display: flex; flex-wrap: wrap; gap: .5rem 2rem; margin-top: 1rem; padding-top: .9rem; border-top: 1px solid {LINE}; }}
.az-stat {{ flex: 0 1 auto; min-width: 0; }}
.az-stat .n {{ font-size: 1.35rem; font-weight: 650; font-variant-numeric: tabular-nums; }}
.az-stat .n small {{ font-size: .85rem; font-weight: 500; color: {MUTED}; }}
.az-mix {{ display: flex; height: 8px; border-radius: 4px; overflow: hidden; margin: .45rem 0 .35rem; background: #E9EEF1; width: 100%; }}
.az-mix span {{ display: block; height: 100%; }}
.az-mixkey span {{ margin-right: .9rem; white-space: nowrap; font-size: .86rem; }}

/* Hotel tiles: a calm row. Name, number, which way it moved, how many reviews it rests on. */
.az-card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 10px; padding: .95rem 1.05rem; height: 100%; }}
[data-testid="stHorizontalBlock"] {{ align-items: stretch; }}
[data-testid="stColumn"] > div, [data-testid="stColumn"] [data-testid="stVerticalBlock"],
[data-testid="stColumn"] [data-testid="stElementContainer"], [data-testid="stColumn"] [data-testid="stMarkdown"],
[data-testid="stColumn"] [data-testid="stMarkdown"] > div,
[data-testid="stColumn"] [data-testid="stMarkdownContainer"] {{ height: 100%; }}
.az-card.empty {{ background: transparent; border: 1.5px dashed #C9D3DA; }}
.az-nodata-title {{ font-size: 1rem; line-height: 1.3; color: {INK}; font-weight: 650; margin-top: .2rem; }}
.az-label {{ font-size: .86rem; color: {MUTED} !important; font-weight: 600; }}
.az-card .az-label {{ color: {INK} !important; font-size: .95rem; }}
.az-value {{ font-size: 2.3rem; line-height: 1.1; font-weight: 700; letter-spacing: -0.03em; color: {INK}; margin: .25rem 0 .1rem;
  font-variant-numeric: tabular-nums; }}
.az-value small {{ font-size: .9rem; font-weight: 500; letter-spacing: 0; color: {MUTED}; }}
.az-note {{ font-size: .85rem; color: {MUTED} !important; line-height: 1.45; }}
.az-up {{ color: {GOOD} !important; font-weight: 650; }}
.az-down {{ color: {BAD} !important; font-weight: 650; }}
.az-flat {{ color: {MUTED} !important; font-weight: 650; }}
.az-badge {{ display: inline-block; font-size: .76rem; font-weight: 600; padding: .08rem .5rem; border-radius: 999px;
  border: 1px solid transparent; margin: .25rem .3rem 0 0; white-space: nowrap; }}
.az-badge.warn {{ background: {WARN_BG}; color: {WARN} !important; border-color: #EBCB82; }}
.az-badge.good {{ background: {GOOD_BG}; color: {GOOD} !important; border-color: #A9D3BC; }}
.az-badge.bad {{ background: {BAD_BG}; color: {BAD} !important; border-color: #E5ADA7; }}
.az-badge.neutral {{ background: #EEF2F4; color: {MUTED} !important; border-color: {LINE}; }}
.az-complaint {{ margin-top: .6rem; padding-top: .55rem; border-top: 1px solid {LINE}; }}

/* Things worth a look: plain sentences with a coloured mark, most urgent first. */
.az-insight {{ display: flex; gap: .75rem; align-items: baseline; padding: .7rem 0; border-bottom: 1px solid {LINE}; }}
.az-insight:last-child {{ border-bottom: 0; }}
.az-insight .tag {{ flex: 0 0 8.5rem; font-size: .84rem; font-weight: 650; white-space: nowrap; }}
.az-insight.alert .tag {{ color: {BAD} !important; }}
.az-insight.good .tag {{ color: {GOOD} !important; }}
.az-insight.info .tag {{ color: {TEAL} !important; }}
.az-insight .body {{ line-height: 1.5; max-width: 46rem; }}
.az-list {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 10px; padding: .2rem 1.1rem; }}

/* Review cards */
.az-review {{ background: {CARD}; border: 1px solid {LINE}; border-radius: 10px; padding: .95rem 1.1rem; margin-bottom: .7rem; line-height: 1.5; }}
.az-review .meta {{ font-size: .84rem; color: {MUTED} !important; margin: .15rem 0 .5rem 0; }}
.az-review .head {{ display: flex; flex-wrap: wrap; gap: .55rem; align-items: center; }}
.az-score {{ font-weight: 700; font-size: .95rem; padding: .1rem .55rem; border-radius: 6px; font-variant-numeric: tabular-nums; }}
.az-score.good {{ background: {GOOD_BG}; color: {GOOD} !important; }}
.az-score.warn {{ background: {WARN_BG}; color: {WARN} !important; }}
.az-score.bad {{ background: {BAD_BG}; color: {BAD} !important; }}
.az-liked, .az-disliked, .az-reply {{ padding: .3rem 0 .3rem .8rem; margin: .45rem 0; border-left: 3px solid; }}
.az-liked {{ border-color: {GOOD}; }}
.az-disliked {{ border-color: {BAD}; }}
.az-reply {{ border-color: {TEAL}; background: #EEF4FA; padding: .45rem .8rem; border-radius: 0 6px 6px 0; }}
.az-liked .h, .az-disliked .h, .az-reply .h {{ font-weight: 650; font-size: .82rem; }}
.az-liked .h {{ color: {GOOD} !important; }}
.az-disliked .h {{ color: {BAD} !important; }}
.az-reply .h {{ color: {TEAL} !important; }}
.az-chip {{ display: inline-block; font-size: .78rem; padding: .06rem .5rem; border-radius: 999px; margin: .3rem .3rem 0 0; font-weight: 600; }}
.az-chip.neg {{ background: {BAD_BG}; color: {BAD} !important; }}
.az-chip.pos {{ background: {GOOD_BG}; color: {GOOD} !important; }}
:focus-visible {{ outline: 2px solid {TEAL} !important; outline-offset: 2px; }}
@media (max-width: 640px) {{
  .az-big {{ font-size: 3.2rem; }}
  .az-value {{ font-size: 1.9rem; }}
  .az-hero {{ padding: 1rem; }}
  .az-insight {{ flex-direction: column; gap: .15rem; }}
  .az-insight .tag {{ flex: none; }}
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
