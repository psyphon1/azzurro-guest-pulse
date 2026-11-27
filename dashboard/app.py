"""Azzurro Hotels guest-review dashboard. Run with:  streamlit run dashboard/app.py

Database: env REVIEWS_DB (default data/reviews.db). A file name containing "demo" triggers the demo banner.
"""
import sys
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:  # `streamlit run` only puts dashboard/ on the path
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from dashboard.ui import data as D  # noqa: E402
from dashboard.ui.style import CSS, esc  # noqa: E402

st.set_page_config(page_title="Azzurro Review Insights", layout="wide", initial_sidebar_state="expanded")
st.markdown(CSS, unsafe_allow_html=True)
st.title("Azzurro Hotels: guest review insights")
st.markdown('<div class="az-sub">A weekly view of what guests say on Booking.com, built for Monday-morning reviews.</div>',
            unsafe_allow_html=True)

try:
    from insights import metrics as m  # noqa: E402
    from dashboard.ui import sections as S  # noqa: E402
except ImportError as exc:
    st.error("The review analysis module is not available yet, so the dashboard cannot show numbers.")
    st.caption(f"Technical detail for the team: {exc}")
    st.stop()

from scraper.config import PROPERTIES  # noqa: E402

db_path = D.resolve_db_path()

# --- no database file ---------------------------------------------------------------------------
if not db_path.exists():
    st.warning(f"No review data found at {db_path}.")
    st.markdown(
        "To get started, collect the reviews first by running this in a terminal:\n\n"
        "```\npython -m scraper.run --property all --mode full\npython -m insights.pipeline --db data/reviews.db\n```\n"
        "Or, to look around with made-up practice data:\n\n"
        "```\npython scripts/make_demo_db.py\npython -m insights.pipeline --db data/demo.db\nREVIEWS_DB=data/demo.db streamlit run dashboard/app.py\n```"
    )
    st.stop()

try:
    bundle = D.load_bundle(db_path)
except Exception as exc:  # unreadable or half-built file: say so politely, no traceback
    st.warning("The review database could not be read. It may be empty or still being created.")
    st.caption(f"Technical detail for the team: {type(exc).__name__}: {exc}")
    st.stop()

df_all, topics_all, health = bundle.reviews, bundle.topics, bundle.health
S.render_banner(db_path, health)

if df_all.empty:
    st.info("There are no reviews in the database yet. Run the review collection first "
            "(python -m scraper.run --property all --mode full), then refresh this page.")
    S.render_health(health, None, {}, {})
    S.render_howto()
    st.stop()

# --- sidebar filters ----------------------------------------------------------------------------
slug_by_name = {p.name: p.slug for p in PROPERTIES}
present = set(df_all["property_name"])
all_names = [p.name for p in PROPERTIES if p.name in present] + sorted(present - set(slug_by_name))
with st.sidebar:
    st.header("Filters")
    sel_names = st.multiselect("Hotels", all_names, default=all_names, key="props",
                               help="Pick one or more hotels. Everything on the page follows this choice.")
    preset = st.selectbox("Time period", D.PRESETS, index=0, key="range_preset",
                          help="Weeks run Monday to Sunday (Sydney time). The default is the latest finished week.")

first, last = df_all["review_date"].min().date(), df_all["review_date"].max().date()
try:
    latest_week = m.latest_complete_week(df_all)
except Exception:
    latest_week = None
if latest_week is None or pd.isna(latest_week):
    latest_week = D.monday_of(last) - timedelta(days=7)

custom = None
if preset == "Custom dates":
    with st.sidebar:
        picked = st.date_input("From and to", value=(latest_week, latest_week + timedelta(days=6)), key="custom_range")
    custom = tuple(picked) if isinstance(picked, (tuple, list)) and len(picked) == 2 else None
    if custom is None:
        st.info("Pick both a start and an end date in the sidebar.")
        st.stop()
start, end, focus = D.preset_range(preset, latest_week, D.sydney_today(), first, last, custom)
with st.sidebar:
    st.caption(f"Showing {D.nice_range(start, end)}.")
    st.caption(f"Data file: {db_path.name}")

if not sel_names:
    st.info("Choose at least one hotel in the sidebar.")
    st.stop()

sel_slugs = [slug_by_name.get(n, n) for n in sel_names]
df = df_all[df_all["property_name"].isin(sel_names)]
topics = topics_all[topics_all["review_key"].isin(df["review_key"])] if not topics_all.empty else topics_all
topics_ready = not topics_all.empty
labels = D.topic_labels()
df_range = df[(df["review_date"] >= pd.Timestamp(start)) & (df["review_date"] <= pd.Timestamp(end))]

if df_range.empty:
    st.info(f"No reviews between {D.nice_range(start, end)} for the selected hotels. "
            "Try a longer time period (for example Last 12 weeks or All time) or select more hotels.")
    S.render_health(health, None, {}, {})
    S.render_howto()
    st.stop()

week_label = D.nice_range(focus, focus + timedelta(days=6))
if preset == "This week so far":
    week_label += " (week not finished)"

# --- 2-4: the focus week ------------------------------------------------------------------------
S.render_insights(m.generate_insights(df, topics, focus), week_label)

st.header("Guest score")
if start < focus or end > focus + timedelta(days=6):
    st.caption(f"The score cards and hotel cards describe the week of {week_label}. Trends, topics and the review feed cover {D.nice_range(start, end)}.")
S.render_kpis(m.compare_weeks(df, focus))

breakdown = m.property_breakdown(df, focus)
if breakdown is not None and not breakdown.empty:
    breakdown = breakdown[breakdown["property"].isin(sel_slugs)]
top_complaint: dict = {}
if topics_ready and breakdown is not None:
    for r in breakdown.itertuples(index=False):
        if int(r.n) == 0:
            continue
        ts = m.topic_shares(df, topics, focus, focus + timedelta(days=6), polarity="negative", properties=[r.property])
        extra = S.no_comment_count(ts)
        ts = ts[ts["count"] > 0] if ts is not None and not ts.empty else ts
        if ts is not None and not ts.empty:
            top = ts.sort_values("count", ascending=False).iloc[0]
            top_complaint[r.property] = (f"{top['label']} ({int(top['count'])} of {int(top['n_reviews'])} "
                                         f"negative reviews with a comment)", extra)
S.render_properties(breakdown, top_complaint, topics_ready)

# --- 5-6: range-wide views ----------------------------------------------------------------------
trend_start = min(start, D.monday_of(end) - timedelta(weeks=7))
S.render_trends(m.weekly_trend(df, trend_start, end), trend_start, end)
S.render_topics(df, topics, start, end, sel_names, sel_slugs, topics_ready, db_path)

# --- 7-9: feed, health, help --------------------------------------------------------------------
chips = D.topic_chips(topics)
feed_df = S.render_feed(df_range, chips, labels, topics_ready)
S.render_health(health, feed_df, chips, labels)
S.render_howto()
