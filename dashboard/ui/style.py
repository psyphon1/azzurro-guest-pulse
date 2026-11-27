"""Look and feel: one stylesheet plus tiny HTML helpers.

All text that comes from the database (reviews, replies, error messages) MUST go through `esc()`
before it is placed inside HTML, because the dashboard renders cards with unsafe_allow_html.
"""
from __future__ import annotations

import html
import re

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
_T = TOKENS
_S = _T["space"]

CSS = f"""
<style>
@font-face {{ font-family: 'Inter'; font-style: normal; font-weight: 100 900; font-display: swap;
  src: url('app/static/fonts/inter-latin-wght-normal.woff2') format('woff2'); }}
:root {{ color-scheme: light; --ink: {INK}; --muted: {MUTED}; --line: {LINE}; --accent: {TEAL}; }}
.stApp {{ background: {PAPER}; color: {INK}; }}
.stApp, .stApp p, .stApp label, .stApp li, .stApp input, .stApp button, .stApp textarea,
.stApp span:not([data-testid="stIconMaterial"]):not(.material-symbols-rounded) {{ font-family: {FONT}; }}
.stApp, .stApp p, .stApp label, .stApp li, .stApp span {{ color: {INK}; }}
.stApp p, .stApp li, .stApp label {{ font-size: {_T["body"]}px; }}
h1, h1 span {{ font-size: {_T["title"]}px !important; }}
h2, h2 span {{ font-size: {_T["section"]}px !important; }}
[data-testid="stSidebar"], [data-testid="stSidebarCollapsedControl"] {{ display: none; }}
.block-container {{ padding-top: {_S * 8}px; max-width: 1200px; }}
h1, h2, h3 {{ font-family: {FONT}; color: {INK}; letter-spacing: -0.01em; }}
h1 {{ font-size: {_T["title"]}px !important; font-weight: 700 !important; padding: 0 !important; }}
h2 {{ font-size: {_T["section"]}px !important; font-weight: 650 !important; margin-top: {_S * 5}px !important;
  padding: 0 0 {_S}px 0 !important; scroll-margin-top: 140px; }}
h3 {{ font-size: 16px !important; font-weight: 650 !important; }}
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p {{ color: {MUTED} !important;
  font-size: {_T["meta"]}px !important; opacity: 1 !important; }}
:focus-visible {{ outline: 2px solid {TEAL} !important; outline-offset: 2px; }}
/* Primary buttons (Apply filters): white text on the accent blue, darker on hover. */
[data-testid="stBaseButton-primaryFormSubmit"], [data-testid="stBaseButton-primary"] {{
  background: {TEAL} !important; border-color: {TEAL} !important; }}
[data-testid="stBaseButton-primaryFormSubmit"] *, [data-testid="stBaseButton-primary"] * {{
  color: #FFFFFF !important; font-weight: 650 !important; }}
[data-testid="stBaseButton-primaryFormSubmit"]:hover, [data-testid="stBaseButton-primary"]:hover {{
  background: #164F8C !important; border-color: #164F8C !important; }}
[data-testid="stBaseButton-secondaryFormSubmit"], [data-testid="stBaseButton-secondary"] {{
  background: {CARD} !important; border: 1px solid #B7C3CC !important; }}
[data-testid="stBaseButton-secondaryFormSubmit"] *, [data-testid="stBaseButton-secondary"] * {{
  color: {INK} !important; font-weight: 600 !important; }}

/* Sticky filter bar and section nav */
.st-key-az_bar {{ position: sticky; top: 3.75rem; z-index: 990; background: {PAPER}; padding: {_S}px 0 {_S}px 0;
  border-bottom: 1px solid {LINE}; }}
.st-key-az_bar [data-testid="stForm"] {{ border: 0; padding: 0; }}
.az-nav {{ display: flex; flex-wrap: wrap; gap: {_S}px; margin-top: {_S}px; }}
.az-nav span {{ font-size: {_T["meta"]}px; font-weight: 600; color: {MUTED} !important; }}
.az-nav a {{ font-size: 13px; font-weight: 600; color: {TEAL} !important; text-decoration: none;
  padding: 2px {_S}px; border-radius: 999px; background: {_T["accent_bg"]}; }}
.az-nav a:hover {{ text-decoration: underline; }}

.az-sub {{ color: {MUTED} !important; margin: {_S // 2}px 0 {_S * 2}px 0; font-size: {_T["body"]}px; }}
.az-banner-demo {{ background: #22313A; color: #FFE08A !important; font-weight: 700; padding: {_S}px {_S * 2}px;
  border-radius: {_S}px; margin-bottom: {_S}px; }}
.az-banner-demo * {{ color: #FFE08A !important; }}
.az-fresh {{ border-radius: {_S}px; padding: {_S}px {_S * 2}px; margin-bottom: {_S}px; font-size: 13px;
  border: 1px solid {LINE}; background: {CARD}; line-height: 1.5; }}
.az-fresh.warn {{ background: {WARN_BG}; border-color: #EBCB82; }}
.az-fresh ul {{ margin: {_S // 2}px 0 0 {_S * 2}px; padding: 0; }}

/* Cards */
.az-card {{ background: {CARD}; border: 1px solid {LINE}; border-radius: {_T["radius"]}px; padding: {_S * 2}px;
  height: 100%; }}
[data-testid="stHorizontalBlock"] {{ align-items: stretch; }}
[data-testid="stColumn"] > div, [data-testid="stColumn"] [data-testid="stVerticalBlock"],
[data-testid="stColumn"] [data-testid="stElementContainer"], [data-testid="stColumn"] [data-testid="stMarkdown"],
[data-testid="stColumn"] [data-testid="stMarkdown"] > div,
[data-testid="stColumn"] [data-testid="stMarkdownContainer"] {{ height: 100%; }}
.az-card.empty {{ background: #EEF1F3; border: 1px dashed #C5CED5; }}
.az-card.empty * {{ color: {MUTED} !important; }}
.az-label {{ font-size: {_T["meta"]}px; color: {MUTED} !important; font-weight: 600; }}
.az-card .az-name {{ font-size: 15px; font-weight: 650; }}
.az-value {{ font-size: 32px; line-height: 1.15; font-weight: 700; letter-spacing: -0.02em; margin: {_S // 2}px 0;
  font-variant-numeric: tabular-nums; }}
.az-value small {{ font-size: 13px; font-weight: 500; color: {MUTED}; letter-spacing: 0; }}
.az-note {{ font-size: {_T["meta"]}px; color: {MUTED} !important; line-height: 1.5; }}
.az-up, .az-good {{ color: {GOOD} !important; font-weight: 650; }}
.az-down, .az-bad {{ color: {BAD} !important; font-weight: 650; }}
.az-flat {{ color: {MUTED} !important; font-weight: 650; }}
.az-spark {{ font-size: 18px; letter-spacing: 1px; color: {TEAL} !important; line-height: 1; margin-top: {_S}px; }}
.az-badge {{ display: inline-block; font-size: 11px; font-weight: 650; padding: 1px {_S}px; border-radius: 999px;
  border: 1px solid transparent; margin: {_S // 2}px {_S // 2}px 0 0; white-space: nowrap; }}
.az-badge.warn {{ background: {WARN_BG}; color: {WARN} !important; border-color: #EBCB82; }}
.az-badge.good {{ background: {GOOD_BG}; color: {GOOD} !important; border-color: #A9D3BC; }}
.az-badge.bad {{ background: {BAD_BG}; color: {BAD} !important; border-color: #E5ADA7; }}
.az-badge.neutral {{ background: #EEF2F4; color: {MUTED} !important; border-color: {LINE}; }}

/* Worth a look: action rows */
.az-insight {{ display: flex; gap: {_S * 1.5}px; align-items: baseline; line-height: 1.5; padding: {_S}px 0; }}
.az-insight .tag {{ flex: 0 0 120px; font-size: {_T["meta"]}px; font-weight: 700; white-space: nowrap; }}
.az-insight.alert .tag {{ color: {BAD} !important; }}
.az-insight.good .tag {{ color: {GOOD} !important; }}
.az-insight.info .tag {{ color: {TEAL} !important; }}
.az-insight.safety .tag {{ color: #FFFFFF !important; background: {BAD}; border-radius: 999px; padding: 0 {_S}px;
  flex: 0 0 auto; }}

/* Review feed rows: the expander under each row is a quiet "Read full review" link, not a big box */
[data-testid="stExpander"] details {{ border: 0 !important; background: transparent; }}
[data-testid="stExpander"] summary {{ padding: 0 0 {_S}px 0 !important; font-size: {_T["meta"]}px; color: {TEAL}; }}
[data-testid="stExpander"] summary p {{ font-size: {_T["meta"]}px !important; color: {TEAL} !important; font-weight: 600; }}
/* Review feed rows */
.az-row b, .az-row .az-note {{ font-size: 13px; }}
.az-row {{ display: flex; flex-wrap: wrap; gap: {_S}px; align-items: center; padding: {_S}px 0 {_S // 2}px 0;
  border-top: 1px solid {LINE}; }}
.az-row .snip {{ flex: 1 1 320px; color: {INK} !important; font-size: {_T["body"]}px; overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; min-width: 0; }}
.az-score {{ font-weight: 700; font-size: 13px; padding: 1px {_S}px; border-radius: 999px;
  font-variant-numeric: tabular-nums; }}
.az-score.good {{ background: {GOOD_BG}; color: {GOOD} !important; }}
.az-score.warn {{ background: {WARN_BG}; color: {WARN} !important; }}
.az-score.bad {{ background: {BAD_BG}; color: {BAD} !important; }}
.az-review {{ line-height: 1.55; }}
.az-review .meta {{ font-size: {_T["meta"]}px; color: {MUTED} !important; margin-bottom: {_S}px; }}
.az-liked, .az-disliked, .az-reply {{ padding: {_S // 2}px 0 {_S // 2}px {_S * 1.5}px; margin: {_S}px 0;
  border-left: 3px solid; }}
.az-liked {{ border-color: {GOOD}; }}
.az-disliked {{ border-color: {BAD}; }}
.az-reply {{ border-color: {TEAL}; background: {_T["accent_bg"]}; padding: {_S}px {_S * 1.5}px; border-radius: 0 {_S}px {_S}px 0; }}
.az-liked .h, .az-disliked .h, .az-reply .h {{ font-weight: 650; font-size: {_T["meta"]}px; }}
.az-liked .h {{ color: {GOOD} !important; }}
.az-disliked .h {{ color: {BAD} !important; }}
.az-reply .h {{ color: {TEAL} !important; }}
.az-chip {{ display: inline-block; font-size: 11px; padding: 1px {_S}px; border-radius: 999px; margin: 0 {_S // 2}px 0 0;
  font-weight: 600; white-space: nowrap; }}
.az-chip.neg {{ background: {BAD_BG}; color: {BAD} !important; }}
.az-chip.pos {{ background: {GOOD_BG}; color: {GOOD} !important; }}
.az-chip.safety {{ background: {BAD}; color: #FFFFFF !important; }}
@media (max-width: 640px) {{
  .az-insight {{ flex-direction: column; gap: 0; }}
  .az-insight .tag {{ flex: none; }}
  .st-key-az_bar {{ position: static; }}
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
