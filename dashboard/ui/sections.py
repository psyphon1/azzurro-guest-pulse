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
DATA_AGE_WARN_DAYS = 7      # newest review this many days behind today: say so
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
def render_banner(db_path: Path, health: pd.DataFrame, no_data: dict | None = None) -> None:
    """Top of the page: freshness, then (in plain sentences) which hotels have no reviews or only part of the history.
    `no_data` is slug -> D.NoData; when omitted it is worked out from the health table (nothing stored)."""
    if "demo" in db_path.name.lower():
        html('<div class="az-banner-demo">DEMO DATA: synthetic, not real guest reviews</div>')
    if health is None or health.empty:
        html('<div class="az-fresh warn"><b>Data freshness:</b> no update history found yet.</div>')
        return
    if no_data is None:
        no_data = D.hotels_without_reviews(health)
    ok = pd.to_datetime(health["last_ok_at"], utc=True, errors="coerce")
    latest = ok.max()
    when = D.to_sydney(latest) if pd.notna(latest) else "never"
    short = [f"{nd.name}: no reviews collected yet." for nd in no_data.values()]     # the summary line
    problems = [f"{nd.name}: no reviews collected yet. {nd.reason} It is not included in any number on this page."
                for nd in no_data.values()]                                            # the details
    for r in health.itertuples(index=False):
        if r.property in no_data:      # said above, once, in plain words
            continue
        name = r.property_name
        line = None
        if r.latest_status == "blocked":
            line = f"{name}: Booking.com blocked our last check, so recent reviews may be missing."
        elif r.latest_status == "failed":
            line = f"{name}: the last update failed, so recent reviews may be missing."
        if bool(r.stale):
            line = (line + " " if line else "") + f"{name}: no successful update for more than 48 hours."
        if line:
            short.append(line)
            problems.append(line)
    last_ok = f"Last successful update: {esc(when)} (Sydney time)." if pd.notna(latest) else "No successful update yet."
    # Hotels whose older reviews were not collected: say so plainly, never silently show partial history.
    partial = [(r.property_name, f"{r.property_name}: only part of the history is collected. {r.coverage_note}")
               for r in health.itertuples(index=False)
               if r.property not in no_data and isinstance(r.coverage_note, str) and r.coverage_note]
    summary = " ".join(esc(x) for x in dict.fromkeys(short))
    if partial:
        summary += (f' <b>Not every review is included</b> for {esc(names_phrase([n for n, _ in partial]))}: '
                    f'older reviews are missing, so long-term numbers cover only part of the history.')
    if problems:
        html(f'<div class="az-fresh warn"><b>&#9888; Check the data before you rely on it.</b> {summary}</div>')
    else:
        html(f'<div class="az-fresh"><b>&#10003; Data is up to date.</b> <span class="more">{last_ok}</span> {summary}</div>')
    if problems or partial:
        with st.expander("Details: what is missing and why"):
            items = "".join(f"<li>{esc(x)}</li>" for x in list(dict.fromkeys(problems)) + [t for _, t in partial])
            html(f'<div class="az-note">{last_ok}</div><ul class="az-note">{items}</ul>')


def coverage_text(selected: list[tuple[str, str]], breakdown: pd.DataFrame | None, no_data: dict,
                  period: str = "this week") -> str:
    """'Based on 3 of 4 hotels. Not included: Central Sydney (no reviews collected yet).'
    `selected` is [(slug, name)] for the hotels the staff member chose; a hotel counts when it has reviews in the week shown."""
    n_by = {} if breakdown is None or breakdown.empty else dict(zip(breakdown["property"], breakdown["n"].astype(int)))
    total = len(selected)
    covered = sum(1 for slug, _ in selected if n_by.get(slug, 0) > 0)
    out = f"Based on {covered} of {total} hotels." if total != 1 else f"Based on {covered} of 1 hotel."
    left_out = [f"{name} ({'no reviews collected yet' if slug in no_data else 'no reviews ' + period})"
                for slug, name in selected if n_by.get(slug, 0) == 0]
    if left_out:
        out += " Not included: " + ", ".join(left_out) + "."
    return out


def names_phrase(names: list[str]) -> str:
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def nodata_note(no_data_names: list[str], where: str) -> None:
    """A one-line caption naming the hotels that have no reviews and so cannot appear in `where`."""
    if no_data_names:
        verb = "has" if len(no_data_names) == 1 else "have"
        st.caption(f"{esc(names_phrase(no_data_names))} {verb} no reviews collected, so "
                   f"{'it is' if len(no_data_names) == 1 else 'they are'} not in {where}.")


def render_skipped(n: int) -> None:
    if n:
        st.caption(f"{n:,} stored review{'s were' if n != 1 else ' was'} skipped because the date or score could not "
                   "be trusted (unreadable, from the future, or outside 1 to 10). They are not counted anywhere.")


# 2. Insights --------------------------------------------------------------------------------
def render_week_header(week_label: str, coverage: str = "", lab: D.WeekLabels | None = None) -> None:
    """The heading over the week's answer, with one short line saying which week and which hotels it covers."""
    st.subheader(lab.heading if lab else "This week at a glance")
    line = f"Week of {week_label}."
    if coverage:
        line += " " + coverage
    st.caption(esc(line))


def render_insights(insights: list, week_label: str = "", coverage: str = "", lab: D.WeekLabels | None = None) -> None:
    st.subheader("Worth a look")
    if lab is not None and not lab.current:
        st.caption('Most urgent first. "This week" below means the week shown above.')
    else:
        st.caption("Most urgent first.")
    if not insights:
        empty_note(f"Nothing stands out {lab.in_week if lab else 'this week'}, or there are not enough reviews yet to say.")
        return
    order = {"alert": 0, "good": 1, "info": 2}
    tags = {"alert": "&#9650; Needs attention", "good": "&#10003; Good news", "info": "&#8505; For your info"}
    # The overall average is already the big number above: repeating it here is noise.
    insights = [i for i in insights if not (getattr(i, "property", None) is None and i.text.startswith("Average rating"))]
    if not insights:
        empty_note("Nothing else stands out for this week.")
        return
    rows = []
    for ins in sorted(insights, key=lambda i: order.get(i.kind, 3)):
        kind = ins.kind if ins.kind in tags else "info"
        n_txt = f' <span class="az-note">Based on {esc(reviews_word(ins.n))}.</span>' if ins.n is not None else ""
        rows.append(f'<div class="az-insight {kind}"><div class="tag">{tags[kind]}</div>'
                    f'<div class="body">{esc(ins.text)}{n_txt}</div></div>')
    html(f'<div class="az-list">{"".join(rows)}</div>')


# 3. KPIs ------------------------------------------------------------------------------------
def _scale_pos(score: float) -> float:
    """Where a 1 to 10 score sits along the scale bar, in percent."""
    return max(0.0, min(100.0, (float(score) - 1) / 9 * 100))


def score_scale(cur: float | None, prev: float | None) -> str:
    """Booking.com's 1 to 10 scale with this week's score (solid dot) and the week before (dashed ring)."""
    if cur is None or pd.isna(cur):
        return ""
    was = "" if prev is None or pd.isna(prev) else f'<span class="was" style="left:{_scale_pos(prev):.1f}%"></span>'
    label = f"Score {cur:.1f} on a 1 to 10 scale" + ("" if not was else f", previous week {prev:.1f}")
    ticks = "".join(f'<span style="left:{_scale_pos(v):.1f}%">{v}</span>' for v in (1, 5, 8, 10))
    key = (f'Negative under {m.NEGATIVE_BELOW:g}, mixed {m.NEGATIVE_BELOW:g} to {m.POSITIVE_FROM:g}, '
           f'positive from {m.POSITIVE_FROM:g}.' + (" Solid dot: this week. Ring: the week before." if was else ""))
    return (f'<div class="az-scale" role="img" aria-label="{esc(label)}">'
            f'<span class="now" style="left:{_scale_pos(cur):.1f}%"></span>{was}</div>'
            f'<div class="az-ticks">{ticks}</div><div class="az-key">{esc(key)}</div>')


def render_kpis(cmp, lab: D.WeekLabels | None = None) -> None:
    """The week's answer in one block: the score, which way it moved, how many reviews it rests on, and the mix."""
    cur, prev = cmp.current, cmp.previous
    lab = lab or D.week_labels(D.monday_of(D.today_sydney()), D.today_sydney())
    small = cur.n < m.LOW_SAMPLE_BELOW or (cmp.delta is not None and prev.n < m.LOW_SAMPLE_BELOW)
    caution = badge("Small sample", "warn", "Very few reviews: one guest can swing this number.") if cur.n and small else ""
    if cur.avg_rating is None:
        verdict = f'No reviews {esc(lab.in_week)}.'
        big = '<div class="az-big">&ndash;</div>'
    else:
        prev_txt = "no reviews" if prev.avg_rating is None else f"{prev.avg_rating:.1f} from {reviews_word(prev.n)}"
        verdict = (f'{change_html(cmp.delta)} <span class="az-note">Change vs previous week. '
                   f'{esc(lab.previous)}: {esc(prev_txt)}.</span>{caution}')
        big = f'<div class="az-big">{cur.avg_rating:.1f}<small> / 10</small></div>'
    if cur.n:
        def pct(k):
            return round(100 * k / cur.n)
        mix = (f'<div class="az-mix" role="img" aria-label="Positive {cur.positive}, mixed {cur.mixed}, negative {cur.negative}">'
               f'<span style="width:{100 * cur.positive / cur.n}%;background:{POS_COL}"></span>'
               f'<span style="width:{100 * cur.mixed / cur.n}%;background:{MIX_COL}"></span>'
               f'<span style="width:{100 * cur.negative / cur.n}%;background:{NEG_COL}"></span></div>'
               f'<div class="az-mixkey"><span style="color:{GOOD}">Positive {cur.positive} of {cur.n} ({pct(cur.positive)}%)</span>'
               f'<span style="color:{WARN}">Mixed {cur.mixed} of {cur.n} ({pct(cur.mixed)}%)</span>'
               f'<span style="color:{BAD}">Negative {cur.negative} of {cur.n} ({pct(cur.negative)}%)</span></div>')
    else:
        mix = f'<div class="az-note">No reviews {esc(lab.in_week)}.</div>'
    html(f'<div class="az-hero"><div class="az-label">{esc(lab.score)}</div>'
         f'<div class="row">{big}<div class="verdict">{verdict}</div></div>'
         f'{score_scale(cur.avg_rating, prev.avg_rating)}'
         f'<div class="az-stats"><div class="az-stat"><div class="az-label">{esc(lab.count)}</div>'
         f'<div class="n">{cur.n}<small> ({esc(lab.prior)}: {prev.n})</small></div></div>'
         f'<div class="az-stat" style="flex:1 1 14rem"><div class="az-label">Positive vs negative</div>{mix}</div></div></div>')


def week_so_far_sentence(cur, ref, today: date, focus: date) -> str:
    """One plain sentence about the unfinished current week, set beside the focus week `ref`."""
    start = D.monday_of(today)
    head = f"This week so far ({D.short_day(start)} to today): {cur.avg_rating:.1f} from {reviews_word(cur.n)}"
    if ref.avg_rating is None:
        head += f". There were no reviews in the week of {D.short_day(focus)} to compare with."
    else:
        last_full = focus == start - timedelta(days=7)
        which = "the last full week" if last_full else f"the week of {D.short_day(focus)}"
        head += f", compared with {ref.avg_rating:.1f} for {which}."
    head += " A part-week average moves more, so read it with the count."
    if cur.n < m.LOW_SAMPLE_BELOW:
        head += (f" Only {reviews_word(cur.n)} so far, so treat this as a hint, not a trend.")
    return head


def render_week_so_far(cur, ref, today: date, focus: date) -> None:
    """A compact strip under the score cards: the live week, when the cards describe an older, finished week.
    Shown only if the live week already has at least one review among the selected hotels."""
    if cur is None or cur.n == 0 or cur.avg_rating is None:
        return
    html(f'<div class="az-fresh" style="margin-top:.6rem">{esc(week_so_far_sentence(cur, ref, today, focus))}</div>')


def render_data_age(newest: date, today: date) -> None:
    """Say how old the newest review is when it is a week or more behind the clock, so a stale snapshot is never
    mistaken for this week's data."""
    days = (today - newest).days
    if days < DATA_AGE_WARN_DAYS:
        return
    html(f'<div class="az-fresh warn"><b>&#9888; This data is not current.</b> The newest review in this data is from '
         f'{esc(D.short_day(newest))} {newest.year}, {days} days ago, so the numbers below describe an earlier '
         f'week, not the week in progress.</div>')


# 4. Properties ------------------------------------------------------------------------------
def no_data_card(nd) -> str:
    detail = f'<div class="az-note" style="margin-top:.4rem">What our system recorded: {esc(nd.detail)}</div>' if nd.detail else ""
    return (f'<div class="az-card empty"><div class="az-label">{esc(nd.name)}</div>'
            f'<div style="margin:.3rem 0">{badge("No data", "bad", "Nothing has been collected for this hotel.")}</div>'
            f'<div class="az-nodata-title">No reviews collected for this hotel yet</div>'
            f'<div class="az-note" style="margin-top:.3rem">{esc(nd.reason)}</div>{detail}</div>')


def render_properties(breakdown: pd.DataFrame, top_complaint: dict[str, tuple[str, int]], topics_ready: bool,
                      no_data: dict | None = None, order: list[str] | None = None,
                      lab: D.WeekLabels | None = None) -> None:
    """One card per hotel. `no_data` (slug -> D.NoData) adds a card for each hotel with no reviews at all;
    `order` is the slug order to draw them in (default: the breakdown's order, then the empty hotels)."""
    st.subheader("How each hotel is doing")
    st.caption("Same week as above, compared with the week before.")
    lab = lab or D.week_labels(D.monday_of(D.today_sydney()), D.today_sydney())
    no_data = no_data or {}
    by_slug = {} if breakdown is None or breakdown.empty else {r.property: r for r in breakdown.itertuples(index=False)}
    slugs = [x for x in (order if order is not None else list(by_slug) + [k for k in no_data if k not in by_slug])
             if x in by_slug or x in no_data]
    if not slugs:
        empty_note("No hotels to show for the current selection.")
        return
    cols = st.columns(min(len(slugs), 4))
    for i, slug in enumerate(slugs):
        with cols[i % len(cols)]:
            if slug not in by_slug:
                html(no_data_card(no_data[slug]))
                continue
            r = by_slug[slug]
            n = int(r.n)
            if n:
                complaint = top_complaint.get(r.property) if topics_ready else None
                if not topics_ready:
                    ctext = "Topic analysis has not been run yet."
                elif complaint:
                    ctext = f"Top complaint: <b style='color:{INK}'>{esc(complaint[0])}</b>"
                    if complaint[1]:
                        ctext += (f'<br>{complaint[1]} more negative '
                                  f'review{"s" if complaint[1] != 1 else ""} had no comment.')
                else:
                    ctext = f"No complaint topics found {lab.in_week}."
                body = (f'<div class="az-value">{fmt_score(r.avg_rating)}<small> / 10</small></div>'
                        f'<div>{change_html(r.delta)}</div>'
                        f'<div class="az-note">{esc(reviews_word(n))} {esc(lab.in_week)}, {int(r.prev_n)} {esc(lab.prior_in)}</div>'
                        f'<div>{low_badge(n)}</div><div class="az-note az-complaint">{ctext}</div>')
            else:
                body = f'<div class="az-note" style="margin-top:.6rem">No reviews {esc(lab.in_week)}.</div>'
            html(f'<div class="az-card"><div class="az-label">{esc(r.property_name)}</div>{body}</div>')


# 5. Trends ----------------------------------------------------------------------------------
def render_trends(trend: pd.DataFrame, start: date, end: date, no_data_names: list[str] | None = None) -> None:
    st.header("Trends")
    st.caption(f"Each point is one week (Monday to Sunday). Shows at least the last 8 weeks, up to {end.strftime('%d %b %Y')}.")
    nodata_note(no_data_names or [], "these trends")
    if trend is None or trend.empty or trend["n"].sum() == 0:
        empty_note("No reviews in this period, so there is no trend to draw.")
        return
    t = trend.copy()
    t["label"] = pd.to_datetime(t["week_start"]).dt.strftime("%d %b")
    left, right = st.columns(2)
    with left:
        st.markdown("**Average guest score per week**")
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_bar(x=t["label"], y=t["n"], name="Reviews received", marker_color="#D5DEE5",
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
        st.plotly_chart(plotly_layout(fig), width="stretch")
        st.caption("Grey bars and the numbers on them show how many reviews each week's score is based on. Weeks with only a few reviews are less reliable.")
    with right:
        st.markdown("**Positive, mixed and negative reviews per week**")
        fig = go.Figure()
        for col, name, color, pattern in (
            ("positive", f"Positive ({m.POSITIVE_FROM:g} or more)", POS_COL, ""),
            ("mixed", f"Mixed ({m.NEGATIVE_BELOW:g} to under {m.POSITIVE_FROM:g})", MIX_COL, "/"),
            ("negative", f"Negative (under {m.NEGATIVE_BELOW:g})", NEG_COL, "x"),
        ):
            fig.add_bar(x=t["label"], y=t[col], name=name, marker=dict(color=color, pattern=dict(shape=pattern, fillmode="overlay", fgcolor="rgba(255,255,255,.6)", solidity=0.25)),
                        text=t[col].where(t[col] > 0, None), textposition="inside", insidetextanchor="middle",
                        hovertemplate="Week of %{x}<br>" + name + ": %{y}<extra></extra>")
        fig.update_layout(barmode="stack")
        fig.update_xaxes(type="category", title_text="Week starting (Monday)")
        fig.update_yaxes(title_text="Number of reviews")
        st.plotly_chart(plotly_layout(fig), width="stretch")
        st.caption("Colours also differ by pattern: solid = positive, diagonal lines = mixed, crosses = negative.")


# 6. Topics ----------------------------------------------------------------------------------
def render_topics(df: pd.DataFrame, topics: pd.DataFrame, start: date, end: date, prop_names: list[str],
                  prop_slugs: list[str], topics_ready: bool, db_path: Path,
                  no_data_names: list[str] | None = None) -> None:
    st.header("What guests talk about")
    nodata_note(no_data_names or [], "these charts")
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
    counts = m.comment_counts(df, start, end, polarity=polarity, properties=prop_slugs)
    non_english = int(getattr(counts, "n_non_english", 0) or 0)     # same rule as the pipeline; 0 until it exists
    if non_english:
        many = non_english != 1
        st.caption(f"{non_english} of {counts.n_with_comment} {sent} reviews with a comment in this period "
                   f"{'are' if many else 'is'} not in English, so {'they are' if many else 'it is'} left out of these "
                   f"topic counts. The totals in the chart labels still include {'them' if many else 'it'}.")
    left, right = st.columns([1.1, 1])
    with left:
        st.markdown(f"**Top {'complaints' if polarity == 'negative' else 'things guests praise'}**")
        s = shares[shares["count"] > 0].sort_values("count") if shares is not None and not shares.empty else None
        if s is None or s.empty:
            empty_note(f"No {view.lower()} found in this period.")
        else:
            labels = [f"{int(r['count'])} of {int(r['n_reviews'])} ({round(100 * r['share'])}%)"
                      + (", small sample" if r["low_sample"] else "") for _, r in s.iterrows()]
            fig = go.Figure(go.Bar(x=s["count"], y=s["label"], orientation="h", marker_color=color,
                                   text=labels, textposition="outside", cliponaxis=False,
                                   hovertemplate="%{y}<br>%{text}<extra></extra>"))
            fig.update_xaxes(title_text="Number of reviews mentioning it", range=[0, s["count"].max() * 1.6],
                             dtick=max(1, int(s["count"].max() // 6) or 1))
            st.plotly_chart(plotly_layout(fig, 380), width="stretch")
            st.caption(f"\"2 of 6\" means 2 of the 6 {sent} reviews with a comment mentioned it. "
                       f"One review can mention several topics.")
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
            st.plotly_chart(plotly_layout(fig, 380), width="stretch")
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


def render_feed(df_range: pd.DataFrame, chips: dict, labels: dict[str, str], topics_ready: bool,
                no_data_names: list[str] | None = None) -> pd.DataFrame:
    """Draw the review feed and return the filtered frame (used for the CSV download)."""
    st.header("Review feed")
    st.caption("Guest reviews in the selected dates and hotels. Reviewer names are never stored.")
    nodata_note(no_data_names or [], "this feed")
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


MAX_REPEAT_NOTICES = 3
REPEAT_SAMPLE_CHARS = 80


def month_year(ts) -> str:
    return pd.Timestamp(ts).strftime("%b %Y") if pd.notna(ts) else "an unknown date"


def repeated_notice(r) -> str:
    """One plain sentence (HTML-safe) about a group of reviews that share a score and text, plus a short sample.
    The sample is guest text: control characters out, email and phone masked, cut to 80 characters, then escaped."""
    first, last = month_year(r.first_date), month_year(r.last_date)
    span = first if first == last else f"{first} to {last}"
    sample = mask_pii(clean_text(r.sample_text, 500)).strip()
    cut = sample[:REPEAT_SAMPLE_CHARS] + ("..." if len(sample) > REPEAT_SAMPLE_CHARS else "")
    example = f' Example: &ldquo;{esc(cut)}&rdquo;' if sample else ""
    return (f"&#8505; Repeated reviews: {int(r.n)} reviews at {esc(r.property_name)} share the same score and "
            f"text ({esc(span)}). They are included in every number on this page; read them in the feed before "
            f"drawing conclusions.{example}")


def render_repeated(repeated: pd.DataFrame | None) -> None:
    if repeated is None or repeated.empty:
        return
    for r in repeated.head(MAX_REPEAT_NOTICES).itertuples(index=False):
        html(f'<div class="az-fresh">{repeated_notice(r)}</div>')


def render_health(health: pd.DataFrame, feed_df: pd.DataFrame | None, chips: dict, labels: dict[str, str],
                  repeated: pd.DataFrame | None = None) -> None:
    st.header("Data health")
    st.caption("When each hotel's reviews were last collected, and whether the last attempt worked.")
    render_repeated(repeated)
    if health is None or health.empty:
        empty_note("No update history yet.")
    else:
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
cannot be sorted into topics, so topic counts say "of N reviews with a comment". Topic tags are only given to reviews written in English (the key words are English), so reviews in
other languages get no tags; the Topics section says how many reviews that leaves out.

**Privacy.** Reviewer names are never stored, and neither are photos. Guests sometimes type an email address or phone number into
their review text: these are hidden before anything is shown or downloaded (an email appears as `j***@***.com`, a phone number as
"[phone removed]"). The filter is a best effort, so please do not copy review text into other systems without reading it first.
Review text is shown as plain text only: links and formatting in a review never work.
"""
        )
