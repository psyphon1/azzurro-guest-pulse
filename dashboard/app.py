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

st.set_page_config(page_title="Azzurro Review Insights", layout="wide", initial_sidebar_state="collapsed")
st.markdown(CSS, unsafe_allow_html=True)

log = logging.getLogger("azzurro.dashboard")
FRIENDLY_CRASH = ("Something went wrong while building this page, so it could not be shown. "
                  "Please refresh. If it keeps happening, tell the team (the details are in the server log).")

try:
    from insights import metrics as m  # noqa: E402
    from dashboard.ui import views as V  # noqa: E402
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

def _apply_filters() -> None:
    """Apply filters button: copy the filter-bar widgets into the applied filters and the URL."""
    ss = st.session_state
    custom = ss.get("f_custom")
    custom = tuple(custom) if isinstance(custom, (tuple, list)) and len(custom) == 2 else None
    ss["applied"] = {"period": ss.get("f_period", D.DEFAULT_PERIOD), "names": list(ss.get("f_hotels") or []),
                     "custom": custom}
    ss["feed_page"] = 1


def _clear_filters() -> None:
    """Clear filters button: back to the default view, everywhere (filter bar, feed, URL)."""
    ss = st.session_state
    ss["f_period"], ss["f_hotels"] = D.DEFAULT_PERIOD, []
    ss["applied"] = {"period": D.DEFAULT_PERIOD, "names": [], "custom": None}
    for key, value in (("feed_pills", []), ("feed_topic", ""), ("feed_search", ""), ("feed_hotel", None),
                       ("feed_page", 1)):
        ss[key] = value


def _open_in_feed(action: dict) -> None:
    st.session_state["feed_preset"] = action


def render_dashboard(db_path, bundle) -> None:
    today = D.today_sydney()      # one reading of the Sydney clock for the whole run
    df_all, skipped = D.clean_reviews(bundle.reviews, today)
    topics_all, health = D.clean_topics(bundle.topics, df_all), bundle.health
    no_data = D.hotels_without_reviews(health, df_all)     # hotels with no usable review at all (e.g. blocked)
    repeated = m.repeated_reviews(df_all) if hasattr(m, "repeated_reviews") and not df_all.empty else None
    slug_by_name = {p.name: p.slug for p in PROPERTIES}
    if not df_all.empty:
        slug_by_name.update(dict(zip(df_all["property_name"], df_all["property"])))
    present = set(df_all["property_name"]) if not df_all.empty else set()
    all_names = [p.name for p in PROPERTIES] + sorted(present - {p.name for p in PROPERTIES})
    all_slugs = [slug_by_name[n] for n in all_names]
    name_by_slug = {v: k for k, v in slug_by_name.items()}

    V.render_header(db_path, health, no_data, skipped, repeated, len(PROPERTIES))

    # Applied filters: from the URL on the first visit, then only changed by the Apply / Clear buttons.
    ss = st.session_state
    if "applied" not in ss:
        period, slugs, custom = D.parse_query(dict(st.query_params), all_slugs)
        names = [name_by_slug[s] for s in slugs] if slugs else []
        ss["applied"] = {"period": period, "names": names, "custom": custom}
        ss["f_period"], ss["f_hotels"] = period, names
        if custom:
            ss["f_custom"] = custom
    if "f_custom" not in ss:
        ss["f_custom"] = (D.monday_of(today), today)
    V.render_filter_bar(all_names, _apply_filters, _clear_filters, today)
    applied = ss["applied"]
    period = applied["period"] if applied.get("period") in D.PERIODS else D.DEFAULT_PERIOD
    sel_names = [n for n in applied.get("names") or [] if n in all_names] or all_names
    sel_slugs = [slug_by_name.get(n, n) for n in sel_names]
    st.query_params.from_dict(D.to_query(period, sel_slugs, all_slugs, applied.get("custom")))

    if df_all.empty:
        st.info("There are no reviews in the database yet. Run the review collection first "
                "(python -m scraper.run --property all --mode full), then refresh this page.")
        V.render_health_table(health)
        V.render_howto()
        st.stop()

    first, last = df_all["review_date"].min().date(), df_all["review_date"].max().date()
    start, end, focus = D.period_range(period, today, first, last, applied.get("custom"))
    sel_nodata = {s: nd for s, nd in no_data.items() if s in sel_slugs}
    nodata_names = [nd.name for nd in sel_nodata.values()]
    df = df_all[df_all["property"].isin(sel_slugs)]
    topics = topics_all[topics_all["review_key"].isin(df["review_key"])] if not topics_all.empty else topics_all
    topics_ready = not topics_all.empty
    labels = D.topic_labels()

    # --- overview -------------------------------------------------------------------------------------------
    st.header(D.period_label(period, start, end, today), anchor="overview")
    if df.empty:
        st.info("No reviews have been collected for the selected hotels yet. Choose another hotel above.")
        V.render_hotels([], sel_nodata, sel_slugs)
        V.render_health_table(health)
        V.render_howto()
        st.stop()
    newest = df["review_date"].max().date()
    if (today - newest).days >= 7:
        st.warning(f"The newest review in this data is from {D.short_day(newest)} {newest.year}, "
                   f"{(today - newest).days} days ago. Pick an earlier period or All time to see reviews.")
    covered = sorted(set(sel_slugs) - set(sel_nodata))
    if nodata_names:
        st.caption(f"Based on {len(covered)} of {len(sel_slugs)} hotels. Not included: "
                   f"{', '.join(nodata_names)} (no reviews collected yet).")
    V.render_kpis(D.kpis(df, start, end, today))
    df_range = df[(df["review_date"] >= pd.Timestamp(start)) & (df["review_date"] <= pd.Timestamp(end))]
    V.render_worth_a_look(m.generate_insights(df, topics, focus), _open_in_feed)

    # --- hotels, trends, topics -----------------------------------------------------------------------------
    rows = D.hotel_rows(df, topics, [s for s in sel_slugs if s not in sel_nodata], name_by_slug, start, end, labels)
    V.render_hotels(rows, sel_nodata, sel_slugs)
    trend_start = min(start, D.monday_of(end) - timedelta(weeks=7))
    V.render_trends(m.weekly_trend(df, trend_start, end), nodata_names)
    V.render_topics(df, topics, start, end, [(s, name_by_slug.get(s, s)) for s in covered], topics_ready,
                    nodata_names)

    # --- feed, health, help ---------------------------------------------------------------------------------
    chips = D.topic_chips(topics)
    V.render_feed(df_range, chips, labels, topics_ready, set(sel_slugs), name_by_slug)
    V.render_health_table(health)
    V.render_howto()


try:
    render_dashboard(db_path, bundle)
except Exception:   # st.stop() is not an Exception, so it passes straight through. Anything else: no traceback.
    log.exception("dashboard failed while rendering")
    st.error(FRIENDLY_CRASH)
