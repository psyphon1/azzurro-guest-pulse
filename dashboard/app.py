"""Azzurro Hotels guest-review dashboard. Run with:  streamlit run dashboard/app.py

Database: env REVIEWS_DB, else data/reviews.db, else data/sample/reviews_sample.db (the public snapshot), all
relative to the project root. A file name containing "demo" triggers the demo banner, "sample" the snapshot banner.
"""
import logging
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

log = logging.getLogger("azzurro.dashboard")
FRIENDLY_CRASH = ("Something went wrong while building this page, so it could not be shown. "
                  "Please refresh. If it keeps happening, tell the team (the details are in the server log).")

try:
    from insights import metrics as m  # noqa: E402
    from dashboard.ui import sections as S  # noqa: E402
except ImportError:
    log.exception("dashboard modules could not be imported")
    st.error("The review analysis module is not available yet, so the dashboard cannot show numbers.")
    st.stop()

from scraper.config import PROPERTIES  # noqa: E402

db_path = D.resolve_db_path()

# --- no database file ---------------------------------------------------------------------------
# Only the file NAME is ever shown to staff: a full path would tell a visitor how the server is laid out.
if not db_path.exists():
    st.warning(f"No review data found (looked for the file {esc(db_path.name)}).")
    st.markdown(
        "To get started, collect the reviews first by running this in a terminal:\n\n"
        "```\npython -m scraper.run --property all --mode full\npython -m insights.pipeline --db data/reviews.db\n```\n"
        "Or, to look around with made-up practice data:\n\n"
        "```\npython scripts/make_demo_db.py\npython -m insights.pipeline --db data/demo.db\nREVIEWS_DB=data/demo.db streamlit run dashboard/app.py\n```"
    )
    st.stop()

try:
    bundle = D.load_bundle(db_path)
except Exception:  # unreadable, corrupt or half-built file: say so politely; the details go to the server log only
    log.exception("review database could not be read")
    st.warning("The review database could not be read. It may be empty, damaged, not a review database, "
               "or still being created. Please try again in a minute.")
    st.stop()

def render_dashboard(db_path, bundle) -> None:
    today = D.today_sydney()      # one reading of the Sydney clock for the whole run
    df_all, skipped = D.clean_reviews(bundle.reviews, today)
    topics_all, health = D.clean_topics(bundle.topics, df_all), bundle.health
    if D.is_sample(db_path):     # a snapshot must never be mistaken for live data: say so above everything else
        S.html(f'<div class="az-banner-demo">{esc(D.sample_banner_text(health))}</div>')
    no_data = D.hotels_without_reviews(health, df_all)     # hotels with no usable review at all (e.g. blocked)
    S.render_banner(db_path, health, no_data)
    S.render_skipped(skipped)
    # Disclosure only (the other module may not have this yet): groups of reviews that share a score and text.
    repeated = m.repeated_reviews(df_all) if hasattr(m, "repeated_reviews") and not df_all.empty else None

    if df_all.empty:
        st.info("There are no reviews in the database yet. Run the review collection first "
                "(python -m scraper.run --property all --mode full), then refresh this page.")
        S.render_health(health, None, {}, {}, repeated)
        S.render_howto()
        st.stop()

    # --- sidebar filters ----------------------------------------------------------------------------
    slug_by_name = {**dict(zip(df_all["property_name"], df_all["property"])), **{p.name: p.slug for p in PROPERTIES}}
    present = set(df_all["property_name"])
    # Every configured hotel is listed, even one with no reviews: it must never silently disappear.
    all_names = [p.name for p in PROPERTIES] + sorted(present - {p.name for p in PROPERTIES})
    with st.sidebar:
        st.header("Filters")
        sel_names = st.multiselect("Hotels", all_names, default=all_names, key="props",
                                   help="Pick one or more hotels. Everything on the page follows this choice.")
        preset = st.selectbox("Time period", D.PRESETS, index=0, key="range_preset",
                              help="Weeks run Monday to Sunday (Sydney time). The default is the latest finished week.")

    first, last = df_all["review_date"].min().date(), df_all["review_date"].max().date()
    try:
        latest_week = m.latest_complete_week(df_all, today)
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
    start, end, focus = D.preset_range(preset, latest_week, today, first, last, custom)
    with st.sidebar:
        st.caption(f"Showing {D.nice_range(start, end)}.")
        st.caption(f"Data file: {esc(db_path.name)}")

    if not sel_names:
        st.info("Choose at least one hotel in the sidebar.")
        st.stop()

    sel_slugs = [slug_by_name.get(n, n) for n in sel_names]
    sel_nodata = {slug: nd for slug, nd in no_data.items() if slug in sel_slugs}
    nodata_names = [nd.name for nd in sel_nodata.values()]
    df = df_all[df_all["property_name"].isin(sel_names)]
    topics = topics_all[topics_all["review_key"].isin(df["review_key"])] if not topics_all.empty else topics_all
    topics_ready = not topics_all.empty

    if df.empty:     # only hotels without any reviews are selected
        many = len(sel_nodata) != 1
        st.info(f"No reviews have been collected for the selected hotel{'s' if many else ''} yet, so there are no "
                "scores, trends or topics to show. The card below says why. Select another hotel in the sidebar to see its reviews.")
        S.render_properties(None, {}, topics_ready, sel_nodata, sel_slugs)
        S.render_health(health, None, {}, {}, repeated)
        S.render_howto()
        st.stop()
    S.render_data_age(df["review_date"].max().date(), today)
    labels = D.topic_labels()
    df_range = df[(df["review_date"] >= pd.Timestamp(start)) & (df["review_date"] <= pd.Timestamp(end))]

    if df_range.empty:
        st.info(f"No reviews between {D.nice_range(start, end)} for the selected hotels. "
                "Try a longer time period (for example Last 12 weeks or All time) or select more hotels.")
        S.render_health(health, None, {}, {}, repeated)
        S.render_howto()
        st.stop()

    lab = D.week_labels(focus, today)
    week_label = D.nice_range(focus, focus + timedelta(days=6))
    if lab.current:
        week_label += " (week not finished)"

    # --- 2-4: the focus week ------------------------------------------------------------------------
    breakdown = m.property_breakdown(df, focus)
    if breakdown is not None and not breakdown.empty:
        breakdown = breakdown[breakdown["property"].isin(sel_slugs)]
    coverage = S.coverage_text(list(zip(sel_slugs, sel_names)), breakdown, no_data, lab.in_week)
    S.render_insights(m.generate_insights(df, topics, focus), week_label, coverage, lab)

    st.header("Guest score")
    if start < focus or end > focus + timedelta(days=6):
        st.caption(f"The score cards and hotel cards describe the week of {week_label}. Trends, topics and the review feed cover {D.nice_range(start, end)}.")
    elif not lab.current:
        st.caption(f"The score cards and hotel cards describe the week of {week_label}. It is a finished week, not the week in progress.")
    st.caption(coverage)
    S.render_kpis(m.compare_weeks(df, focus), lab)
    if not lab.current:
        S.render_week_so_far(m.week_summary(df, D.monday_of(today)), m.week_summary(df, focus), today, focus)

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
    S.render_properties(breakdown, top_complaint, topics_ready, sel_nodata, sel_slugs, lab)

    # --- 5-6: range-wide views ----------------------------------------------------------------------
    trend_start = min(start, D.monday_of(end) - timedelta(weeks=7))
    S.render_trends(m.weekly_trend(df, trend_start, end), trend_start, end, nodata_names)
    S.render_topics(df, topics, start, end, sel_names, sel_slugs, topics_ready, db_path, nodata_names)

    # --- 7-9: feed, health, help --------------------------------------------------------------------
    chips = D.topic_chips(topics)
    feed_df = S.render_feed(df_range, chips, labels, topics_ready, nodata_names)
    S.render_health(health, feed_df, chips, labels, repeated)
    S.render_howto()


try:
    render_dashboard(db_path, bundle)
except Exception:   # st.stop() is not an Exception, so it passes straight through. Anything else: no traceback.
    log.exception("dashboard failed while rendering")
    st.error(FRIENDLY_CRASH)
