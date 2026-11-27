"""Page sections. Each function draws one block of the dashboard from data already computed by insights.metrics."""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from insights import metrics as m
from dashboard.ui import data as D
from dashboard.ui.privacy import mask_pii
from dashboard.ui.style import (BAD, GOOD, INK, LINE, MUTED, TEAL, WARN, badge, clean_text, esc, one_line, plain_text)

PAGE_SIZE = 10
POS_COL, MIX_COL, NEG_COL = GOOD, "#D9A027", BAD


def html(markup: str) -> None:
    st.markdown(one_line(markup), unsafe_allow_html=True)


def fmt_score(x) -> str:
    return "No reviews" if x is None or pd.isna(x) else f"{x:.1f}"


def reviews_word(n: int) -> str:
    return f"{n} review" + ("" if n == 1 else "s")


def low_badge(n: int) -> str:
    if n < m.LOW_SAMPLE_BELOW:
        return badge("Small sample", "warn",
                     f"Fewer than {m.LOW_SAMPLE_BELOW} reviews: one guest can swing this number. Treat it as a hint, not a trend.")
    return ""


def change_html(delta) -> str:
    if delta is None or pd.isna(delta):
        return '<span class="az-flat">&#9644; No comparison</span> <span class="az-note">(a week has no reviews)</span>'
    if abs(delta) < 0.05:
        return '<span class="az-flat">&#9644; No change</span>'
    if delta > 0:
        return f'<span class="az-up">&#9650; Up {delta:.1f} points</span>'
    return f'<span class="az-down">&#9660; Down {abs(delta):.1f} points</span>'


def plotly_layout(fig: go.Figure, height: int = 360) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=30, b=10), paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)", font=dict(color=INK, size=13),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0), hoverlabel=dict(font_size=13),
    )
    fig.update_xaxes(gridcolor=LINE, linecolor=LINE)
    fig.update_yaxes(gridcolor=LINE, linecolor=LINE)
    return fig


def no_comment_count(shares: pd.DataFrame) -> int:
    """Reviews in the sentiment band with no written text. `n_band_total` may be absent in older metrics."""
    if shares is None or shares.empty or "n_band_total" not in shares.columns:
        return 0
    return max(0, int(shares["n_band_total"].iloc[0]) - int(shares["n_reviews"].iloc[0]))


def empty_note(text: str) -> None:
    st.info(text)


# 1. Banner ----------------------------------------------------------------------------------
def render_banner(db_path: Path, health: pd.DataFrame) -> None:
    if "demo" in db_path.name.lower():
        html('<div class="az-banner-demo">DEMO DATA: synthetic, not real guest reviews</div>')
    if health is None or health.empty:
        html('<div class="az-fresh warn"><b>Data freshness:</b> no update history found yet.</div>')
        return
    ok = pd.to_datetime(health["last_ok_at"], utc=True, errors="coerce")
    latest = ok.max()
    when = D.to_sydney(latest) if pd.notna(latest) else "never"
    problems = []
    for r in health.itertuples(index=False):
        name = r.property_name
        if r.latest_status == "blocked":
            problems.append(f"{name}: Booking.com blocked our last check, so recent reviews may be missing.")
        elif r.latest_status == "failed":
            problems.append(f"{name}: the last update failed, so recent reviews may be missing.")
        if bool(r.stale):
            problems.append(f"{name}: no successful update for more than 48 hours.")
    if problems:
        items = "".join(f"<li>{esc(p)}</li>" for p in dict.fromkeys(problems))
        html(f'<div class="az-fresh warn"><b>&#9888; Check the data before you rely on it.</b> '
             f'Last successful update: {esc(when)} (Sydney time).<ul style="margin:.3rem 0 0 1.1rem">{items}</ul></div>')
    else:
        html(f'<div class="az-fresh"><b>&#10003; Data is up to date.</b> Last successful update: {esc(when)} (Sydney time).</div>')
    # Hotels with more reviews than the collection page limit: say so plainly, never silently show partial history.
    notes = [f"{r.property_name}: {r.coverage_note}" for r in health.itertuples(index=False)
             if isinstance(r.coverage_note, str) and r.coverage_note]
    if notes:
        items = "".join(f"<li>{esc(n)}</li>" for n in notes)
        html(f'<div class="az-fresh"><b>&#8505; Not every review is included.</b> To keep collection fast and polite we only '
             f'read the newest reviews first. Recent weeks are complete; long-term history is not.'
             f'<ul style="margin:.3rem 0 0 1.1rem">{items}</ul></div>')


def render_skipped(n: int) -> None:
    if n:
        st.caption(f"{n:,} stored review{'s were' if n != 1 else ' was'} skipped because the date or score could not "
                   "be trusted (unreadable, from the future, or outside 1 to 10). They are not counted anywhere.")


# 2. Insights --------------------------------------------------------------------------------
def render_insights(insights: list, week_label: str) -> None:
    st.subheader("This week at a glance")
    st.caption(f"Week of {week_label}. The most important things first.")
    if not insights:
        empty_note("Nothing stands out this week, or there are not enough reviews yet to say.")
        return
    order = {"alert": 0, "good": 1, "info": 2}
    tags = {"alert": "&#9650; Needs attention", "good": "&#10003; Good news", "info": "&#8505; For your info"}
    for ins in sorted(insights, key=lambda i: order.get(i.kind, 3)):
        kind = ins.kind if ins.kind in tags else "info"
        n_txt = f'<div class="az-note">Based on {esc(reviews_word(ins.n))}.</div>' if ins.n is not None else ""
        html(f'<div class="az-insight {kind}"><div class="tag">{tags[kind]}</div>'
             f'<div>{esc(ins.text)}{n_txt}</div></div>')


# 3. KPIs ------------------------------------------------------------------------------------
def render_kpis(cmp) -> None:
    cur, prev = cmp.current, cmp.previous
    cols = st.columns([1, 1, 1.1, 0.9, 1.6])
    with cols[0]:
        html(f'<div class="az-card"><div class="az-label">Guest score this week</div>'
             f'<div class="az-value">{fmt_score(cur.avg_rating)}<small>{"" if cur.avg_rating is None else " / 10"}</small></div>'
             f'<div class="az-note">based on {reviews_word(cur.n)}</div>{low_badge(cur.n) if cur.n else ""}</div>')
    with cols[1]:
        html(f'<div class="az-card"><div class="az-label">Previous week</div>'
             f'<div class="az-value">{fmt_score(prev.avg_rating)}<small>{"" if prev.avg_rating is None else " / 10"}</small></div>'
             f'<div class="az-note">based on {reviews_word(prev.n)}</div>{low_badge(prev.n) if prev.n else ""}</div>')
    with cols[2]:
        caution = ""
        if cmp.delta is not None and (cur.n < m.LOW_SAMPLE_BELOW or prev.n < m.LOW_SAMPLE_BELOW):
            caution = "<div>" + badge("Small sample", "warn", "One of the two weeks has very few reviews.") + "</div>"
        html(f'<div class="az-card"><div class="az-label">Change vs previous week</div>'
             f'<div class="az-value" style="font-size:1.5rem">{change_html(cmp.delta)}</div>{caution}'
             f'<div class="az-note">Average score, 1 to 10 scale</div></div>')
    with cols[3]:
        html(f'<div class="az-card"><div class="az-label">Reviews this week</div>'
             f'<div class="az-value">{cur.n}</div><div class="az-note">last week: {prev.n}</div></div>')
    with cols[4]:
        if cur.n:
            def pct(k):
                return round(100 * k / cur.n)
            bar = (f'<div class="az-mix" role="img" aria-label="Positive {cur.positive}, mixed {cur.mixed}, negative {cur.negative}">'
                   f'<span style="width:{100 * cur.positive / cur.n}%;background:{POS_COL}"></span>'
                   f'<span style="width:{100 * cur.mixed / cur.n}%;background:{MIX_COL}"></span>'
                   f'<span style="width:{100 * cur.negative / cur.n}%;background:{NEG_COL}"></span></div>')
            body = (f'{bar}<div class="az-note"><b style="color:{GOOD}">Positive {cur.positive} of {cur.n} ({pct(cur.positive)}%)</b><br>'
                    f'<b style="color:{WARN}">Mixed {cur.mixed} of {cur.n} ({pct(cur.mixed)}%)</b><br>'
                    f'<b style="color:{BAD}">Negative {cur.negative} of {cur.n} ({pct(cur.negative)}%)</b></div>')
            if cur.n < m.LOW_SAMPLE_BELOW:
                body += "<div>" + low_badge(cur.n) + "</div>"
        else:
            body = '<div class="az-note">No reviews this week.</div>'
        html(f'<div class="az-card"><div class="az-label">Positive vs negative</div>{body}</div>')


# 4. Properties ------------------------------------------------------------------------------
def render_properties(breakdown: pd.DataFrame, top_complaint: dict[str, tuple[str, int]], topics_ready: bool) -> None:
    st.subheader("How each hotel is doing")
    st.caption("Same week as above. Compared with the week before.")
    if breakdown is None or breakdown.empty:
        empty_note("No hotels to show for the current selection.")
        return
    rows = list(breakdown.itertuples(index=False))
    cols = st.columns(min(len(rows), 4))
    for i, r in enumerate(rows):
        with cols[i % len(cols)]:
            n = int(r.n)
            if n:
                complaint = top_complaint.get(r.property) if topics_ready else None
                if not topics_ready:
                    ctext = "Topic analysis has not been run yet."
                elif complaint:
                    ctext = f"Top complaint: <b>{esc(complaint[0])}</b>"
                    if complaint[1]:
                        ctext += (f'<br><span style="font-size:.78rem">{complaint[1]} more negative '
                                  f'review{"s" if complaint[1] != 1 else ""} had no comment.</span>')
                else:
                    ctext = "No complaint topics found this week."
                body = (f'<div class="az-value">{fmt_score(r.avg_rating)}<small> / 10</small></div>'
                        f'<div>{change_html(r.delta)}</div>'
                        f'<div class="az-note">{esc(reviews_word(n))} this week, {esc(reviews_word(int(r.prev_n)))} last week</div>'
                        f'<div>{low_badge(n)}</div><div class="az-note" style="margin-top:.4rem">{ctext}</div>')
            else:
                body = '<div class="az-note" style="margin-top:.6rem">No reviews this week.</div>'
            html(f'<div class="az-card"><div class="az-label">{esc(r.property_name)}</div>{body}</div>')


# 5. Trends ----------------------------------------------------------------------------------
def render_trends(trend: pd.DataFrame, start: date, end: date) -> None:
    st.header("Trends")
    st.caption(f"Each point is one week (Monday to Sunday). Shows at least the last 8 weeks, up to {end.strftime('%d %b %Y')}.")
    if trend is None or trend.empty or trend["n"].sum() == 0:
        empty_note("No reviews in this period, so there is no trend to draw.")
        return
    t = trend.copy()
    t["label"] = pd.to_datetime(t["week_start"]).dt.strftime("%d %b")
    left, right = st.columns(2)
    with left:
        st.markdown("**Average guest score per week**")
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_bar(x=t["label"], y=t["n"], name="Reviews received", marker_color="#D9D4C4",
                    text=[f"{int(v)}" for v in t["n"]], textposition="outside", secondary_y=True,
                    hovertemplate="Week of %{x}<br>%{y} reviews<extra></extra>")
        fig.add_scatter(x=t["label"], y=t["avg_rating"], name="Average score", mode="lines+markers+text",
                        line=dict(color=TEAL, width=3), marker=dict(size=9),
                        text=[f"{v:.1f}" if pd.notna(v) else "" for v in t["avg_rating"]], textposition="top center",
                        connectgaps=False, customdata=t["n"],
                        hovertemplate="Week of %{x}<br>Score %{y:.1f} from %{customdata} reviews<extra></extra>")
        fig.add_hline(y=m.POSITIVE_FROM, line_dash="dot", line_color=GOOD,
                      annotation_text=f"Positive from {m.POSITIVE_FROM:g}", annotation_position="bottom right")
        fig.update_yaxes(range=[1, 10.5], title_text="Score (1 to 10)", secondary_y=False)
        fig.update_yaxes(range=[0, max(t["n"].max() * 4, 8)], showgrid=False, showticklabels=False,
                         title_text="", secondary_y=True)
        fig.update_xaxes(type="category", title_text="Week starting (Monday)")
        st.plotly_chart(plotly_layout(fig), use_container_width=True)
        st.caption("Grey bars and the numbers on them show how many reviews each week's score is based on. Weeks with only a few reviews are less reliable.")
    with right:
        st.markdown("**Positive, mixed and negative reviews per week**")
        fig = go.Figure()
        for col, name, color, pattern in (
            ("positive", f"Positive ({m.POSITIVE_FROM:g} or more)", POS_COL, ""),
            ("mixed", f"Mixed ({m.NEGATIVE_BELOW:g} to under {m.POSITIVE_FROM:g})", MIX_COL, "/"),
            ("negative", f"Negative (under {m.NEGATIVE_BELOW:g})", NEG_COL, "x"),
        ):
            fig.add_bar(x=t["label"], y=t[col], name=name, marker=dict(color=color, pattern=dict(shape=pattern, fgcolor="rgba(255,255,255,.55)")),
                        text=t[col].where(t[col] > 0, None), textposition="inside", insidetextanchor="middle",
                        hovertemplate="Week of %{x}<br>" + name + ": %{y}<extra></extra>")
        fig.update_layout(barmode="stack")
        fig.update_xaxes(type="category", title_text="Week starting (Monday)")
        fig.update_yaxes(title_text="Number of reviews")
        st.plotly_chart(plotly_layout(fig), use_container_width=True)
        st.caption("Colours also differ by pattern: solid = positive, diagonal lines = mixed, crosses = negative.")


# 6. Topics ----------------------------------------------------------------------------------
def render_topics(df: pd.DataFrame, topics: pd.DataFrame, start: date, end: date, prop_names: list[str],
                  prop_slugs: list[str], topics_ready: bool, db_path: Path) -> None:
    st.header("What guests talk about")
    if not topics_ready:
        st.info("Topic analysis has not been run yet. Once it has, you will see which issues come up most. "
                f"(For the technical team: python -m insights.pipeline --db data/{esc(db_path.name)})")
        return
    view = st.radio("Show", ["Complaints", "Praise"], horizontal=True, key="topic_view",
                    help="Complaints are topics found in what guests disliked. Praise is what they liked.")
    polarity = "negative" if view == "Complaints" else "positive"
    sent = "negative" if polarity == "negative" else "positive"
    color = BAD if polarity == "negative" else GOOD
    shares = m.topic_shares(df, topics, start, end, polarity=polarity, properties=prop_slugs)
    left, right = st.columns([1.1, 1])
    with left:
        st.markdown(f"**Top {'complaints' if polarity == 'negative' else 'things guests praise'}**")
        s = shares[shares["count"] > 0].sort_values("count") if shares is not None and not shares.empty else None
        if s is None or s.empty:
            empty_note(f"No {view.lower()} found in this period.")
        else:
            labels = [f"{int(r['count'])} of {int(r['n_reviews'])} {sent} reviews with a comment ({round(100 * r['share'])}%)"
                      + (" - small sample" if r["low_sample"] else "") for _, r in s.iterrows()]
            fig = go.Figure(go.Bar(x=s["count"], y=s["label"], orientation="h", marker_color=color,
                                   text=labels, textposition="outside", cliponaxis=False,
                                   hovertemplate="%{y}<br>%{text}<extra></extra>"))
            fig.update_xaxes(title_text="Number of reviews mentioning it", range=[0, s["count"].max() * 2.3], dtick=1)
            st.plotly_chart(plotly_layout(fig, 380), use_container_width=True)
            st.caption(f"Each label reads \"X of Y {sent} reviews with a comment\": how many of the {sent} reviews that "
                       f"include written text mentioned the topic. One review can mention several topics.")
            extra = no_comment_count(shares)
            if extra:
                st.caption(f"{extra} more {sent} review{'s' if extra != 1 else ''} had no comment, so "
                           f"{'it' if extra == 1 else 'they'} cannot be sorted into topics.")
    with right:
        st.markdown("**Which hotel, which topic**")
        hm = m.topic_by_property(df, topics, start, end, polarity=polarity)
        if hm is not None and not hm.empty:
            hm = hm[hm["property_name"].isin(prop_names)]
        if hm is None or hm.empty or hm["count"].sum() == 0:
            empty_note("Nothing to compare yet.")
        else:
            piv = hm.pivot_table(index="property_name", columns="label", values="count", aggfunc="sum", fill_value=0)
            scale = [[0, "#FFFFFF"], [1, "#B3372D" if polarity == "negative" else "#1E7B4F"]]
            fig = go.Figure(go.Heatmap(z=piv.values, x=list(piv.columns), y=list(piv.index), colorscale=scale,
                                       text=piv.values, texttemplate="%{text}", showscale=False, xgap=2, ygap=2,
                                       textfont=dict(size=14),
                                       hovertemplate="%{y}<br>%{x}: %{z} reviews<extra></extra>"))
            fig.update_xaxes(tickangle=-35)
            fig.update_yaxes(autorange="reversed")
            st.plotly_chart(plotly_layout(fig, 380), use_container_width=True)
            st.caption("Numbers are review counts. Darker means more reviews. Compare hotels with care: they receive different numbers of reviews.")


# 7. Feed ------------------------------------------------------------------------------------
def _band_class(band: str) -> tuple[str, str]:
    return {"positive": ("good", "Positive"), "mixed": ("warn", "Mixed"), "negative": ("bad", "Negative")}[band]


def guest_text(value) -> str:
    """Guest-written text, ready for our HTML: hidden characters out, email addresses and phone numbers masked, escaped."""
    return esc(mask_pii(clean_text(value)))


def review_card(r, chips: list, labels: dict[str, str]) -> str:
    cls, word = _band_class(r.band)
    meta = " &middot; ".join(guest_text(x) for x in (r.room_type, r.traveller_type, r.reviewer_country) if x and not pd.isna(x))
    liked = r.liked if r.liked and not pd.isna(r.liked) and str(r.liked).strip() else None
    disliked = r.disliked if r.disliked and not pd.isna(r.disliked) and str(r.disliked).strip() else None
    parts = [f'<div class="az-review"><div class="head"><span class="az-score {cls}">{r.rating:g}/10 &middot; {word}</span>'
             f'<b>{esc(r.property_name)}</b><span class="az-note">{r.review_date.strftime("%a %d %b %Y")}</span></div>']
    if meta:
        parts.append(f'<div class="meta">{meta}</div>')
    if liked is None and disliked is None:
        parts.append('<div class="az-note"><i>Rating only, no written comment.</i></div>')
    else:
        if r.title and not pd.isna(r.title):
            parts.append(f'<div><b>{guest_text(r.title)}</b></div>')
        if liked:
            parts.append(f'<div class="az-liked"><div class="h">&#10003; What guests liked</div>{guest_text(liked)}</div>')
        if disliked:
            parts.append(f'<div class="az-disliked"><div class="h">&#10007; What guests disliked</div>{guest_text(disliked)}</div>')
    if r.has_reply:
        parts.append(f'<div class="az-reply"><div class="h">Hotel reply</div>{guest_text(r.host_reply)}</div>')
    else:
        parts.append("<div style='margin-top:.4rem'>" + badge("No reply yet", "warn", "The hotel has not replied to this review.") + "</div>")
    if chips:
        parts.append("<div>")
        for tid, pol, ev in chips:
            kind, prefix = ("neg", "Complaint") if pol == "negative" else ("pos", "Praise")
            parts.append(f'<span class="az-chip {kind}" title="{guest_text(ev)}">{prefix}: {esc(labels.get(tid, tid))}</span>')
        parts.append("</div>")
    parts.append("</div>")
    return "".join(parts)


def render_feed(df_range: pd.DataFrame, chips: dict, labels: dict[str, str], topics_ready: bool) -> pd.DataFrame:
    """Draw the review feed and return the filtered frame (used for the CSV download)."""
    st.header("Review feed")
    st.caption("Guest reviews in the selected dates and hotels. Reviewer names are never stored.")
    c1, c2, c3 = st.columns([1.3, 1, 1])
    topic_opts = {"": "Any topic"}
    if topics_ready:
        for tid, lab in labels.items():
            topic_opts[f"negative:{tid}"] = f"Complaint: {lab}"
            topic_opts[f"positive:{tid}"] = f"Praise: {lab}"
    with c1:
        topic_choice = st.selectbox("Topic", list(topic_opts), format_func=topic_opts.get, key="feed_topic",
                                    disabled=not topics_ready,
                                    help=None if topics_ready else "Available once topic analysis has been run.")
        search = st.text_input("Search the text", key="feed_search", placeholder="e.g. lift, wifi, breakfast",
                               max_chars=D.MAX_SEARCH_CHARS)
    with c2:
        only_negative = st.checkbox("Only negative reviews", key="feed_neg", help=f"Score under {m.NEGATIVE_BELOW:g}.")
        no_reply = st.checkbox("No reply yet", key="feed_noreply")
        with_comment = st.checkbox("Has written comment", key="feed_text",
                                   help="Hide reviews where the guest only left a score and wrote nothing.")
    with c3:
        sort = st.selectbox("Sort by", ["Newest first", "Lowest score first"], key="feed_sort")
    if not topics_ready:
        st.caption("Topic analysis has not been run yet, so topic tags and the topic filter are switched off.")

    out = D.filter_feed(df_range, chips, topic_choice=topic_choice or None, only_negative=only_negative,
                        no_reply=no_reply, search=search, sort=sort, only_with_comment=with_comment)
    total = len(out)
    sig = (topic_choice, search, only_negative, no_reply, with_comment, sort, len(df_range))
    if st.session_state.get("feed_sig") != sig:
        st.session_state["feed_sig"] = sig
        st.session_state["feed_page"] = 1
    pages = max(1, -(-total // PAGE_SIZE))
    page = D.clamp_page(st.session_state.get("feed_page", 1), pages)
    st.session_state["feed_page"] = page

    if total == 0:
        empty_note("No reviews match these filters. Try clearing a filter.")
        return out
    n_text = int(D.with_comment_mask(out).sum())
    st.markdown(f"**{total} review{'s' if total != 1 else ''}** match ({n_text} with a written comment, {total - n_text} rating only). Page {page} of {pages}.")
    for r in out.iloc[(page - 1) * PAGE_SIZE: page * PAGE_SIZE].itertuples(index=False):
        html(review_card(r, chips.get(r.review_key, []), labels))

    def go_to(delta: int) -> None:
        st.session_state["feed_page"] = D.clamp_page(st.session_state.get("feed_page", 1), 10**9) + delta

    b1, b2, b3 = st.columns([1, 1, 3])
    b1.button("Previous page", disabled=page <= 1, on_click=go_to, args=(-1,), key="feed_prev")
    b2.button("Next page", disabled=page >= pages, on_click=go_to, args=(1,), key="feed_next")
    return out


# 8. Data health -----------------------------------------------------------------------------
_STATUS_WORDS = {"ok": "Working", "blocked": "Blocked by Booking.com", "failed": "Failed", "running": "Running now"}


def render_health(health: pd.DataFrame, feed_df: pd.DataFrame | None, chips: dict, labels: dict[str, str]) -> None:
    st.header("Data health")
    st.caption("When each hotel's reviews were last collected, and whether the last attempt worked.")
    if health is None or health.empty:
        empty_note("No update history yet.")
    else:
        t = pd.DataFrame({
            "Hotel": health["property_name"],
            "Reviews stored": health["stored"],
            "Last successful update (Sydney)": [D.to_sydney(x) for x in health["last_ok_at"]],
            "Latest attempt": [_STATUS_WORDS.get(s, "Never run") if s else "Never run" for s in health["latest_status"]],
            "Up to date?": ["No: over 48 hours old" if s else "Yes" for s in health["stale"].astype(bool)],
            "Coverage": [c if isinstance(c, str) and c else "All reviews Booking.com shows" for c in health["coverage_note"]],
            "Problem details": [plain_text(e) if isinstance(e, str) and e else "" for e in health["latest_error"]],
        })
        st.dataframe(t, hide_index=True, use_container_width=True)
    if feed_df is not None and len(feed_df):
        data, shown = D.feed_to_csv_limited(feed_df, chips, labels)
        if shown < len(feed_df):
            st.warning(f"The download holds only the first {shown:,} of {len(feed_df):,} reviews (newest first). "
                       "Narrow the dates, hotels or filters to get the rest.")
        st.download_button("Download these reviews as CSV", data,
                           file_name="azzurro_reviews.csv", mime="text/csv", key="csv_download",
                           help="Includes the date range, hotels and feed filters currently selected. Opens in Excel.")
    else:
        st.caption("No reviews to download for the current selection.")


# 9. How to read -----------------------------------------------------------------------------
def render_howto() -> None:
    with st.expander("How to read this"):
        st.markdown(
            f"""
**Weeks.** A week runs Monday to Sunday, Sydney time. Each review counts in the week it was published (not the week the guest stayed).
The "latest full week" is the most recent Monday-to-Sunday that has finished.

**Guest score.** The simple average of the 1 to 10 scores on the reviews we collected. It can differ a little from the score Booking.com shows, which is weighted.

**Positive, mixed, negative.**
- Positive: a score of {m.POSITIVE_FROM:g} or higher.
- Mixed: from {m.NEGATIVE_BELOW:g} up to (not including) {m.POSITIVE_FROM:g}.
- Negative: below {m.NEGATIVE_BELOW:g}.

**Small samples.** When a number rests on fewer than {m.LOW_SAMPLE_BELOW} reviews we mark it "Small sample". One unhappy
(or very happy) guest can move a small average a lot, so treat those as a prompt to read the reviews, not as a trend.
Every percentage is shown with its count, for example "2 of 5".

**Topics.** Topics are found automatically by looking for key words in what guests wrote they liked or disliked. It is a
quick guide, not a perfect read: open the review feed to check the actual words. Reviews where the guest left only a score
cannot be sorted into topics, so topic counts say "of N reviews with a comment". Topic key words are mainly English, so reviews in
other languages may get fewer topic tags.

**Privacy.** Reviewer names are never stored, and neither are photos. Guests sometimes type an email address or phone number into
their review text: these are hidden before anything is shown or downloaded (an email appears as `j***@***.com`, a phone number as
"[phone removed]"). The filter is a best effort, so please do not copy review text into other systems without reading it first.
Review text is shown as plain text only: links and formatting in a review never work.
"""
        )
