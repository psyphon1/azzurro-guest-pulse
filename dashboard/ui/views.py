"""Page sections for the single-page dashboard (no sidebar). Numbers come from insights.metrics and
dashboard.ui.data; these functions only lay them out. All database text goes through esc()/guest_text()."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components
from plotly.subplots import make_subplots

from dashboard.ui import data as D
from dashboard.ui.privacy import mask_pii, mask_profanity
from dashboard.ui.style import (BAD, GOOD, INK, LINE, MUTED, TEAL, TOKENS, badge, clean_text, esc, one_line,
                                plain_text)
from insights import metrics as m
from insights.classify import is_low_signal

PAGE_SIZE = 20
POS_COL, MIX_COL, NEG_COL = GOOD, TOKENS["mixed"], BAD
NAV = [("overview", "Overview"), ("hotels", "Hotels"), ("trends", "Trends"), ("topics", "Topics"), ("feed", "Feed")]


def html(markup: str) -> None:
    st.markdown(one_line(markup), unsafe_allow_html=True)


def reviews_word(n: int) -> str:
    return f"{n} review" + ("" if n == 1 else "s")


def small_badge(n: int) -> str:
    if 0 < n < D.SMALL_SAMPLE:
        return badge("Small sample", "warn", f"Fewer than {D.SMALL_SAMPLE} reviews: one guest can move this a lot.")
    return ""


def change_html(delta) -> str:
    if delta is None or pd.isna(delta):
        return '<span class="az-flat">No comparison</span>'
    if abs(delta) < 0.05:
        return '<span class="az-flat">&#9644; No change</span>'
    if delta > 0:
        return f'<span class="az-up">&#9650; Up {delta:.1f}</span>'
    return f'<span class="az-down">&#9660; Down {abs(delta):.1f}</span>'


def plotly_layout(fig: go.Figure, height: int = 320) -> go.Figure:
    fig.update_layout(height=height, margin=dict(l=8, r=8, t=24, b=8), paper_bgcolor="rgba(0,0,0,0)",
                      plot_bgcolor="rgba(0,0,0,0)", font=dict(color=INK, size=12, family="Inter, system-ui, sans-serif"),
                      showlegend=False, hoverlabel=dict(font_size=12))
    fig.update_xaxes(gridcolor=LINE, linecolor=LINE)
    fig.update_yaxes(gridcolor=LINE, linecolor=LINE)
    return fig


# --- header ------------------------------------------------------------------------------------------------------
def health_summary(health: pd.DataFrame | None, no_data: dict, all_count: int) -> tuple[str, bool]:
    """('Data: 3 of 4 hotels', warn?) for the header chip."""
    if health is None or health.empty:
        return "Data: no update history", True
    ok = all_count - len(no_data)
    stale = bool(health["stale"].astype(bool).any()) if "stale" in health.columns else False
    partial = any(isinstance(c, str) and c for c in health.get("coverage_note", []))
    return f"Data: {ok} of {all_count} hotels", bool(no_data) or stale or partial


def render_header(db_path: Path, health: pd.DataFrame | None, no_data: dict, skipped: int,
                  repeated: pd.DataFrame | None, all_count: int) -> None:
    if D.is_sample(db_path):
        html(f'<div class="az-banner-demo">{esc(D.sample_banner_text(health))}</div>')
    if "demo" in db_path.name.lower():
        html('<div class="az-banner-demo">DEMO DATA: synthetic, not real guest reviews</div>')
    left, right = st.columns([4, 1.3], vertical_alignment="center")
    with left:
        st.title("Azzurro Hotels: guest review insights")
    label, warn = health_summary(health, no_data, all_count)
    with right:
        with st.popover(("⚠ " if warn else "✓ ") + label, use_container_width=True):
            render_health_details(health, no_data, skipped, repeated)
        render_fetch(db_path)


def _start_fetch(db_path: Path) -> None:
    from dashboard.ui import collect
    ok, msg = collect.start(db_path)
    st.session_state["fetch_msg"] = (ok, msg)


@st.fragment(run_every=5)
def _fetch_progress() -> None:
    """While a collection runs, check every 5 seconds; reload the whole page when it has finished."""
    from dashboard.ui import collect
    if collect.running():
        st.caption(f"Fetching new reviews ({esc(collect.status().get('state', 'running'))}). "
                   "A browser window opens; the page updates when it finishes.")
        return
    if st.session_state.pop("fetch_watching", False):
        st.rerun()


def render_fetch(db_path: Path) -> None:
    """The "Fetch latest reviews" button (local installs only) and its progress."""
    from dashboard.ui import collect
    ok, why = collect.available(db_path)
    if not ok:
        st.button("Fetch latest reviews", key="fetch", disabled=True, help=why, use_container_width=True)
        return
    busy = collect.running() is not None
    st.button("Fetch latest reviews", key="fetch", type="primary", disabled=busy, use_container_width=True,
              on_click=_start_fetch, args=(db_path,),
              help="Collects new Booking.com reviews for every hotel, adds them to the database and updates "
                   "the topics. Takes a few minutes.")
    msg = st.session_state.pop("fetch_msg", None)
    if msg and not msg[0]:
        st.caption(esc(msg[1]))
    if busy or (msg and msg[0]):
        st.session_state["fetch_watching"] = True
        _fetch_progress()
    else:
        last = collect.status()
        if last.get("state") == "done" and last.get("finished_at"):
            st.caption(f"Last fetch finished {esc(D.to_sydney(last['finished_at']))}.")
        elif last.get("state") == "failed":
            st.caption(f"Last fetch failed: {esc(last.get('error', ''))}")


def render_health_details(health: pd.DataFrame | None, no_data: dict, skipped: int,
                          repeated: pd.DataFrame | None) -> None:
    if health is None or health.empty:
        st.write("No update history yet.")
        return
    ok = pd.to_datetime(health["last_ok_at"], utc=True, errors="coerce").max()
    st.markdown(f"**Last successful update:** {esc(D.to_sydney(ok)) if pd.notna(ok) else 'never'} (Sydney)")
    lines = [f"{nd.name}: no reviews collected yet. {nd.reason}" for nd in no_data.values()]
    for r in health.itertuples(index=False):
        if r.property in no_data:
            continue
        if r.latest_status == "blocked":
            lines.append(f"{r.property_name}: Booking.com blocked the last check; recent reviews may be missing.")
        elif r.latest_status == "failed":
            lines.append(f"{r.property_name}: the last update failed; recent reviews may be missing.")
        if bool(r.stale):
            lines.append(f"{r.property_name}: no successful update for more than 48 hours.")
        if isinstance(r.coverage_note, str) and r.coverage_note:
            lines.append(f"{r.property_name}: only part of the history is collected. {r.coverage_note}")
    if skipped:
        lines.append(f"{skipped:,} stored reviews were skipped (unreadable date or score).")
    if repeated is not None and not repeated.empty:
        for r in repeated.head(3).itertuples(index=False):
            lines.append(f"{int(r.n)} reviews at {r.property_name} share the same score and text; they are counted.")
    if lines:
        html('<ul class="az-list">' + "".join(f"<li>{esc(x)}</li>" for x in lines) + "</ul>")
    else:
        st.write("All hotels are up to date.")


# --- filter bar --------------------------------------------------------------------------------------------------
def period_word(p: str) -> str:
    return "30 days" if p == "Last 30 days" else p


def _show_all_hotels() -> None:
    st.session_state["feed_hotel"] = None


def render_filter_bar(all_names: list[str], on_clear) -> None:
    """Sticky filter bar. Filters apply as soon as they change; Clear resets them."""
    with st.container(key="filters"):
        c1, c2, c3, c4 = st.columns([3, 2, 2, 1], vertical_alignment="bottom")
        with c1:
            st.segmented_control("Period", D.PERIODS, key="f_period", selection_mode="single",
                                 format_func=period_word,
                                 help="Weeks run Monday to Sunday, Sydney time. 30 days = the last 30 days.")
        with c2:
            st.multiselect("Hotels", all_names, key="f_hotels", placeholder="All hotels")
        with c3:
            st.date_input("Custom dates", key="f_custom", format="DD/MM/YYYY", help="Used when Period is Custom.")
        with c4:
            st.button("Clear", key="f_clear", on_click=on_clear, use_container_width=True,
                      help="Back to this week, all hotels, no feed filters.")
        links = "".join(f'<a href="#{a}">{esc(t)}</a>' for a, t in NAV)
        html(f'<div class="az-nav" role="navigation" aria-label="Sections"><span class="lead">Jump to</span>{links}</div>')


# --- overview ----------------------------------------------------------------------------------------------------
def render_kpis(items: list[D.Kpi]) -> None:
    with st.container(key="kpis"):
        cols = st.columns(4)
        for col, k in zip(cols, items):
            cls = {"good": "az-good", "bad": "az-bad"}.get(k.tone, "az-flat")
            arrow = "&#9650; " if (k.delta or 0) > 0 else "&#9660; " if (k.delta or 0) < 0 else ""
            with col:
                html(f'<div class="az-kpi"><div class="label">{esc(k.label)}</div>'
                     f'<div class="value">{esc(k.value)}</div>'
                     f'<div class="delta {cls}">{arrow}{esc(k.delta_text)}</div>'
                     f'<div class="caption"><span>{esc(k.caption)}</span>{small_badge(1) if k.small else ""}</div></div>')


def _action_label(action: dict | None) -> str:
    if not action:
        return ""
    if action.get("safety"):
        return "Show safety reviews"
    if action.get("noreply"):
        return "Show unanswered"
    if action.get("topic"):
        return "Show these reviews"
    if action.get("property"):
        return "Show this hotel"
    return "Show reviews"


def render_worth_a_look(insights: list, on_action) -> None:
    st.subheader("Worth a look")
    # The average score is the first KPI card already: repeating it here is noise.
    items = [i for i in insights if not (getattr(i, "property", None) is None and i.text.startswith("Average rating"))]
    if not items:
        st.caption("Nothing stands out for this period.")
        return
    tags = {"alert": "Needs attention", "good": "Good news", "info": "For your info"}
    with st.container(key="worth"):
        for idx, ins in enumerate(items):
            action = getattr(ins, "action", None)
            safety = bool(action and action.get("safety"))
            kind = "safety" if safety else (ins.kind if ins.kind in tags else "info")
            tag = "Safety" if safety else tags[kind]
            c1, c2, c3 = st.columns([1.3, 7, 2.2], vertical_alignment="center")
            with c1:
                html(f'<span class="az-tag {kind}">{tag}</span>')
            with c2:
                html(f'<div class="az-insight-text">{esc(ins.text)}</div>')
            with c3:
                if action:
                    st.button(_action_label(action), key=f"act_{idx}", on_click=on_action, args=(dict(action),),
                              use_container_width=True)
                else:
                    html('<div class="az-slot"></div>')


# --- hotels ------------------------------------------------------------------------------------------------------
def render_hotels(rows: list[D.HotelRow], no_data: dict, order: list[str]) -> None:
    st.header("Hotels", anchor="hotels")
    by = {r.slug: r for r in rows}
    slugs = [s for s in order if s in by or s in no_data]
    if not slugs:
        st.info("Choose at least one hotel in the filter bar.")
        return
    with st.container(key="hotel_cards"):
        cols = st.columns(min(len(slugs), 4))
        for i, slug in enumerate(slugs):
            with cols[i % len(cols)]:
                if slug not in by:
                    nd = no_data[slug]
                    html(f'<div class="az-hotel empty"><div class="name">{esc(nd.name)}</div>'
                         f'<div class="az-note">No data, blocked by Booking.com</div></div>')
                    continue
                r = by[slug]
                score = "–" if r.avg is None else f"{r.avg:.1f}"
                chip = (f'<span class="az-chip neg" title="Most mentioned complaint">{esc(r.top_complaint)}</span>'
                        if r.top_complaint else '<span class="az-note">No complaint topics</span>')
                html(f'<div class="az-hotel"><div class="name">{esc(r.name)}</div>'
                     f'<div class="score">{score}<small> / 10</small></div>'
                     f'<div class="delta">{change_html(r.delta)}</div>'
                     f'<div class="count">{esc(reviews_word(r.n))} (previous period {r.prev_n})</div>'
                     f'<div class="badge-slot">{small_badge(r.n)}</div>'
                     f'<div class="chip-slot">{chip}</div>'
                     f'<div class="spark"><div class="bars" role="img" aria-label="{esc(r.spark_label)}" '
                     f'title="{esc(r.spark_label)}">{esc(r.spark)}</div><div class="az-note">last 8 weeks</div></div></div>')


# --- trends ------------------------------------------------------------------------------------------------------
def render_trends(trend: pd.DataFrame, nodata_names: list[str]) -> None:
    st.header("Trends", anchor="trends")
    if nodata_names:
        st.caption(f"Not included (no reviews collected): {esc(', '.join(nodata_names))}.")
    if trend is None or trend.empty or trend["n"].sum() == 0:
        st.info("No reviews in this period, so there is no trend to draw.")
        return
    t = trend.copy()
    t["label"] = pd.to_datetime(t["week_start"]).dt.strftime("%d %b")
    left, right = st.columns(2)
    with left:
        st.markdown("**Average score per week**", help="Grey bars: number of reviews each week. "
                    "Weeks with few reviews are less reliable. Dotted line: positive from 8.")
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_bar(x=t["label"], y=t["n"], marker_color="#D5DEE5", text=[f"{int(v)}" for v in t["n"]],
                    textposition="outside", secondary_y=True, hovertemplate="Week of %{x}<br>%{y} reviews<extra></extra>")
        fig.add_scatter(x=t["label"], y=t["avg_rating"], mode="lines+markers+text", line=dict(color=TEAL, width=3),
                        marker=dict(size=8), text=[f"{v:.1f}" if pd.notna(v) else "" for v in t["avg_rating"]],
                        textposition="top center", connectgaps=False, customdata=t["n"],
                        hovertemplate="Week of %{x}<br>Score %{y:.1f} from %{customdata} reviews<extra></extra>")
        fig.add_hline(y=m.POSITIVE_FROM, line_dash="dot", line_color=GOOD)
        fig.update_yaxes(range=[1, 10.5], title_text="Score", secondary_y=False)
        fig.update_yaxes(range=[0, max(t["n"].max() * 4, 8)], showgrid=False, showticklabels=False, secondary_y=True)
        fig.update_xaxes(type="category")
        st.plotly_chart(plotly_layout(fig), width="stretch")
    with right:
        st.markdown("**Positive, mixed and negative per week**",
                    help="Solid green = positive (8+), diagonal amber = mixed (5 to under 8), crossed red = negative.")
        fig = go.Figure()
        for col, name, color, pattern in (("positive", "Positive", POS_COL, ""), ("mixed", "Mixed", MIX_COL, "/"),
                                          ("negative", "Negative", NEG_COL, "x")):
            fig.add_bar(x=t["label"], y=t[col], name=name,
                        marker=dict(color=color, pattern=dict(shape=pattern, fillmode="overlay",
                                                              fgcolor="rgba(255,255,255,.6)", solidity=0.25)),
                        text=t[col].where(t[col] > 0, None), textposition="inside", insidetextanchor="middle",
                        hovertemplate="Week of %{x}<br>" + name + ": %{y}<extra></extra>")
        fig.update_layout(barmode="stack")
        fig.update_xaxes(type="category")
        fig.update_yaxes(title_text="Reviews")
        st.plotly_chart(plotly_layout(fig), width="stretch")
        html('<div class="az-legend"><span class="az-good">&#9632; Positive</span>'
             '<span class="mixed">&#9632; Mixed</span><span class="az-bad">&#9632; Negative</span></div>')


# --- topics ------------------------------------------------------------------------------------------------------
def _bars(s: pd.DataFrame, color: str, sent: str, height: int) -> go.Figure:
    s = s.sort_values("count")
    small = int(s["n_reviews"].iloc[0]) < D.SMALL_SAMPLE if len(s) else True
    text = [f"{int(r['count'])}" if small else f"{int(r['count'])} of {int(r['n_reviews'])} ({round(100 * r['share'])}%)"
            for _, r in s.iterrows()]
    fig = go.Figure(go.Bar(x=s["count"], y=s["label"], orientation="h", marker_color=color, text=text,
                           textposition="outside", cliponaxis=False,
                           hovertemplate="%{y}: %{x} " + sent + " reviews<extra></extra>"))
    fig.update_xaxes(visible=False, range=[0, s["count"].max() * 1.6 if len(s) else 1])
    return plotly_layout(fig, height)


def render_topics(df: pd.DataFrame, topics: pd.DataFrame, start: date, end: date, sel: list[tuple[str, str]],
                  topics_ready: bool, nodata_names: list[str]) -> None:
    st.header("Topics", anchor="topics")
    if not topics_ready:
        st.info("Topic analysis has not been run yet (python -m insights.pipeline).")
        return
    view = st.radio("Show", ["Complaints", "Praise"], horizontal=True, key="topic_view", label_visibility="collapsed")
    polarity = "negative" if view == "Complaints" else "positive"
    color, sent = (BAD, "negative") if polarity == "negative" else (GOOD, "positive")
    slugs = [s for s, _ in sel]
    counts = m.comment_counts(df, start, end, polarity=polarity, properties=slugs)
    not_analysed = int(getattr(counts, "n_not_analysed", 0) or 0)
    notes = []
    if not_analysed:
        notes.append(f"{not_analysed} of {counts.n_with_comment} {sent} reviews with a comment are in a language "
                     "without keywords (not analysed).")
    if nodata_names:
        notes.append(f"Not included (no reviews collected): {', '.join(nodata_names)}.")
    if notes:
        st.caption(esc(" ".join(notes)))
    left, right = st.columns([1, 1.2])
    with left:
        st.markdown("**All selected hotels**", help=f"'3 of 12' = 3 of the 12 {sent} reviews with a written comment "
                    "mentioned it. One review can mention several topics. Percentages hidden under 10 reviews.")
        shares = m.topic_shares(df, topics, start, end, polarity=polarity, properties=slugs)
        s = shares[shares["count"] > 0] if shares is not None and not shares.empty else None
        if s is None or s.empty:
            st.caption(f"No {view.lower()} in this period.")
        else:
            if int(s["n_reviews"].iloc[0]) < D.SMALL_SAMPLE:
                st.caption("Not enough data this period for percentages.")
            st.plotly_chart(_bars(s, color, sent, 40 + 34 * len(s)), width="stretch")
    with right:
        st.markdown("**By hotel**", help="Only topics that were mentioned. Hotels get different numbers of reviews.")
        shown = 0
        for slug, name in sel:
            sh = m.topic_shares(df, topics, start, end, polarity=polarity, properties=[slug])
            sh = sh[sh["count"] > 0] if sh is not None and not sh.empty else sh
            if sh is None or sh.empty:
                continue
            shown += 1
            if int(sh["n_reviews"].iloc[0]) < D.SMALL_SAMPLE:
                st.markdown(f"**{esc(name)}**: not enough data this period ({int(sh['n_reviews'].iloc[0])} "
                            f"{sent} reviews with a comment).")
                continue
            st.markdown(f"**{esc(name)}**")
            st.plotly_chart(_bars(sh.head(5), color, sent, 30 + 30 * min(5, len(sh))), width="stretch",
                            key=f"tb_{slug}_{polarity}")
        if not shown:
            st.caption("Nothing to compare yet.")


# --- feed --------------------------------------------------------------------------------------------------------
def _band(band: str) -> tuple[str, str]:
    return {"positive": ("good", "Positive"), "mixed": ("warn", "Mixed"), "negative": ("bad", "Negative")}[band]


def guest_text(value) -> str:
    return esc(mask_pii(clean_text(value)))


def snippet(r) -> str:
    """One line for the row: disliked first for low scores, else liked; empty answers skipped; profanity masked."""
    parts = [r.title, r.disliked, r.liked] if r.band != "positive" else [r.title, r.liked, r.disliked]
    for p in parts:
        if isinstance(p, str) and p.strip() and not is_low_signal(p):
            return mask_profanity(mask_pii(clean_text(p, 200)))
    return "No comment"


def _chips(chips: list, labels: dict[str, str]) -> str:
    out = []
    for tid, pol, ev in chips:
        if tid == "safety":
            out.append(f'<span class="az-chip safety" title="{guest_text(ev)}">Safety</span>')
            continue
        kind, prefix = ("neg", "Complaint") if pol == "negative" else ("pos", "Praise")
        out.append(f'<span class="az-chip {kind}" title="{guest_text(ev)}">{prefix}: {esc(labels.get(tid, tid))}</span>')
    return "".join(out)


def review_row(r, chips: list, labels: dict[str, str]) -> str:
    cls, word = _band(r.band)
    return (f'<div class="az-row az-review-row"><span class="az-score {cls}">{r.rating:g}/10 {word}</span>'
            f'<b>{esc(r.property_name)}</b><span class="az-note">{r.review_date.strftime("%a %d %b %Y")}</span>'
            f'<span class="snip">{esc(snippet(r))}</span>{_chips(chips, labels)}</div>')


def review_detail(r) -> str:
    meta = ", ".join(guest_text(x) for x in (r.room_type, r.traveller_type, r.reviewer_country)
                     if isinstance(x, str) and x.strip())
    parts = ['<div class="az-review">']
    if meta:
        parts.append(f'<div class="meta">{meta}</div>')
    if isinstance(r.title, str) and r.title.strip():
        parts.append(f"<div><b>{guest_text(r.title)}</b></div>")
    for col, cls, head in (("liked", "az-liked", "&#10003; Liked"), ("disliked", "az-disliked", "&#10007; Disliked")):
        val = getattr(r, col)
        body = guest_text(val) if isinstance(val, str) and val.strip() and not is_low_signal(val) else \
            '<span class="az-nocomment">No comment</span>'
        parts.append(f'<div class="{cls}"><div class="h">{head}</div>{body}</div>')
    if r.has_reply:
        parts.append(f'<div class="az-reply"><div class="h">Hotel reply</div>{guest_text(r.host_reply)}</div>')
    else:
        parts.append(badge("No reply yet", "warn", "The hotel has not replied to this review."))
    parts.append("</div>")
    return "".join(parts)


def render_feed(df_range: pd.DataFrame, chips: dict, labels: dict[str, str], topics_ready: bool,
                valid_slugs: set[str], names: dict[str, str]) -> pd.DataFrame:
    st.header("Review feed", anchor="feed")
    preset = st.session_state.pop("feed_preset", None)
    if preset is not None:
        pills, topic, slug = D.apply_preset(preset, set(labels), valid_slugs)
        st.session_state["feed_pills"] = pills
        st.session_state["feed_topic"] = topic
        st.session_state["feed_hotel"] = slug
        st.session_state["feed_search"] = ""
        what = pills + ([labels.get(topic.split(":")[1], topic)] if topic else []) + \
            ([names.get(slug, slug)] if slug else [])
        st.success(f"Showing reviews from Worth a look: {esc(', '.join(what)) or 'all'}. Use Clear in the filter bar to reset.")
    if st.session_state.pop("scroll_to_feed", False):
        # Jump to this section after a Worth a look button (no external script; runs in the page's own origin).
        components.html("<script>setTimeout(function(){var e=window.parent.document.getElementById('feed');"
                        "if(e){e.scrollIntoView({behavior:'smooth',block:'start'});}},400);</script>", height=0)
    topic_opts = {"": "Any topic"}
    if topics_ready:
        for tid, lab in labels.items():
            topic_opts[f"negative:{tid}"] = f"Complaint: {lab}"
            topic_opts[f"positive:{tid}"] = f"Praise: {lab}"
    if st.session_state.get("feed_topic") not in topic_opts:
        st.session_state["feed_topic"] = ""
    pills = st.pills("Quick filters", D.QUICK_FILTERS, selection_mode="multi", key="feed_pills") or []
    c2, c3, c4 = st.columns([1.6, 1.6, 1.1], vertical_alignment="bottom")
    with c2:
        topic_choice = st.selectbox("Topic", list(topic_opts), format_func=topic_opts.get, key="feed_topic",
                                    disabled=not topics_ready)
    with c3:
        search = st.text_input("Search the text", key="feed_search", placeholder="e.g. lift, wifi, breakfast",
                               max_chars=D.MAX_SEARCH_CHARS)
    with c4:
        sort = st.selectbox("Sort by", ["Newest first", "Lowest score first"], key="feed_sort")
    data = df_range
    slug = st.session_state.get("feed_hotel")
    if slug in valid_slugs:
        data = data[data["property"] == slug]
        a, b = st.columns([5, 1], vertical_alignment="center")
        a.caption(f"Showing {esc(names.get(slug, slug))} only.")
        b.button("Show all hotels", key="feed_hotel_clear", on_click=_show_all_hotels)
    if "Safety" in pills:
        data = data[data["review_key"].isin(D.safety_keys(chips))]
    out = D.filter_feed(data, chips, topic_choice=topic_choice or None, only_negative="Negative" in pills,
                        no_reply="Needs reply" in pills, search=search, sort=sort,
                        only_with_comment="Has comment" in pills)
    total = len(out)
    sig = (tuple(pills), topic_choice, search, sort, slug, len(df_range))
    if st.session_state.get("feed_sig") != sig:
        st.session_state["feed_sig"] = sig
        st.session_state["feed_page"] = 1
    pages = max(1, -(-total // PAGE_SIZE))
    page = D.clamp_page(st.session_state.get("feed_page", 1), pages)
    st.session_state["feed_page"] = page
    if total == 0:
        st.info("No reviews match these filters. Try clearing a filter.")
        return out
    n_text = int(D.with_comment_mask(out).sum())
    st.caption(f"{total} review{'s' if total != 1 else ''} match ({n_text} with a comment). Page {page} of {pages}. "
               "Reviewer names are never stored.")
    for r in out.iloc[(page - 1) * PAGE_SIZE: page * PAGE_SIZE].itertuples(index=False):
        html(review_row(r, chips.get(r.review_key, []), labels))
        with st.expander("Read full review"):
            html(review_detail(r))

    def go_to(delta: int) -> None:
        st.session_state["feed_page"] = D.clamp_page(st.session_state.get("feed_page", 1), 10**9) + delta

    b1, b2, _ = st.columns([1, 1, 4])
    b1.button("Previous page", disabled=page <= 1, on_click=go_to, args=(-1,), key="feed_prev")
    b2.button("Next page", disabled=page >= pages, on_click=go_to, args=(1,), key="feed_next")
    data_csv, shown = D.feed_to_csv_limited(out, chips, labels)
    if shown < total:
        st.caption(f"The download holds the first {shown:,} of {total:,} reviews.")
    st.download_button("Download these reviews as CSV", data_csv, file_name="azzurro_reviews.csv", mime="text/csv",
                       key="csv_download", help="The reviews matching the filters above. Opens in Excel.")
    return out


# --- data health and help ----------------------------------------------------------------------------------------
_STATUS_WORDS = {"ok": "Working", "blocked": "Blocked by Booking.com", "failed": "Failed", "running": "Running now"}


def render_health_table(health: pd.DataFrame | None) -> None:
    st.header("Data health", anchor="health")
    if health is None or health.empty:
        st.caption("No update history yet.")
        return
    never = pd.to_datetime(health["last_ok_at"], utc=True, errors="coerce").isna().tolist()
    empty = (health["stored"].fillna(0).astype(int) == 0).tolist()
    t = pd.DataFrame({
        "Hotel": health["property_name"],
        "Reviews stored": health["stored"],
        "Last successful update (Sydney)": ["Never collected" if nv else D.to_sydney(x)
                                            for x, nv in zip(health["last_ok_at"], never)],
        "Latest attempt": [_STATUS_WORDS.get(s, "Never run") if s else "Never run" for s in health["latest_status"]],
        "Up to date?": ["No: never collected" if nv else "No: over 48 hours old" if s else "Yes"
                        for s, nv in zip(health["stale"].astype(bool), never)],
        "Coverage": ["No reviews collected" if e else c if isinstance(c, str) and c else "All reviews Booking.com shows"
                     for c, e in zip(health["coverage_note"], empty)],
        "Problem details": [plain_text(e) if isinstance(e, str) and e else "" for e in health["latest_error"]],
    })
    st.dataframe(t, hide_index=True, width="stretch")


def render_howto() -> None:
    with st.expander("How to read this"):
        st.markdown(
            f"""
- **Weeks** run Monday to Sunday, Sydney time. A review counts on the day it was published.
- **Score** is the simple average of 1 to 10 scores; Booking.com's own score is weighted, so it can differ.
- **Positive** {m.POSITIVE_FROM:g}+, **mixed** {m.NEGATIVE_BELOW:g} to under {m.POSITIVE_FROM:g}, **negative** under {m.NEGATIVE_BELOW:g}.
- **Small sample**: fewer than {D.SMALL_SAMPLE} reviews. Read the reviews before drawing conclusions.
- **Topics** come from key words in English, French, Spanish, German, Italian and Portuguese; other languages are
  not analysed. Safety & pests (cockroaches, mould, fire risk, theft) is always shown first.
- **Privacy**: reviewer names are never stored. Email addresses and phone numbers are hidden; strong language is
  masked in the one-line preview.
"""
        )
