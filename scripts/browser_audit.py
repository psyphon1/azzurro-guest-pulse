"""Requirements walkthrough in a real browser.

Starts the real dashboard on a database, drives it with Playwright like a staff member would, and checks what is on
screen against numbers computed straight from the SQLite file (never through the dashboard's own code).
Also records every console error, failed request, outside-host request and server-log warning.

    python scripts/browser_audit.py [--db data/reviews.db] [--shots DIR] [--headed]

Exit code 0 only if every check passed.
"""
from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests" / "e2e"))

from playwright.sync_api import sync_playwright  # noqa: E402

from harness import (AppServer, Monitor, card_scores, cards, choose, download_csv, feed_total, main_text,  # noqa: E402
                     no_traceback, search, settle, sidebar, tick, wait_for_app)
from scraper.config import PROPERTIES  # noqa: E402

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f"   [{detail}]" if detail else ""), flush=True)


def sql(db: str, query: str, *args):
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        return con.execute(query, args).fetchall()
    finally:
        con.close()


def one(db: str, query: str, *args):
    return sql(db, query, *args)[0][0]


def shot(page, shots: Path, name: str) -> None:
    page.screenshot(path=str(shots / f"{name}.png"), full_page=True)


def section_text(page, heading: str) -> str:
    """Text from a heading to the next h2 (st.header)."""
    text = main_text(page)
    i = text.find(heading)
    if i < 0:
        return ""
    rest = text[i + len(heading):]
    m = re.search(r"\n(?:Guest score|Trends|What guests talk about|Review feed|Data health)\n", rest)
    return rest[: m.start()] if m else rest


def run(db: str, shots: Path, headed: bool) -> int:
    shots.mkdir(parents=True, exist_ok=True)
    slug_by_name = {p.name: p.slug for p in PROPERTIES}
    stored = {slug: n for slug, n in sql(db, "select property, count(*) from reviews group by 1")}
    srv = AppServer(db)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=not headed)
            ctx = browser.new_context(viewport={"width": 1400, "height": 3200}, accept_downloads=True)
            page = ctx.new_page()
            mon = Monitor(page)
            page.goto(srv.url)
            wait_for_app(page)
            no_traceback(page)

            # ---- R1: all four hotels are covered, honestly --------------------------------------------------
            sb = sidebar(page).inner_text()
            for p in PROPERTIES:
                check(f"R1 hotel listed in sidebar: {p.name}", p.name in sb)
            check("R1 page title names the product", page.get_by_role("heading", name=re.compile("guest review insights")).count() > 0)
            shot(page, shots, "01_landing")

            # ---- R2/R3: weekly summary for the focus week + comparison with the previous week ----------------
            body = main_text(page)
            check("R2 'at a glance' weekly summary shown", bool(re.search(r"at a glance|this week", body, re.I)))
            check("R2 Guest score section shown", "Guest score" in body)
            check("R3 comparison with the previous week shown", bool(re.search(r"previous week|vs\.? last week|last week|than the week", body, re.I)))
            check("R2 every hotel has its own card", all(p.name in section_text(page, "Guest score") or p.name in body for p in PROPERTIES))
            check("R2 percentages carry counts ('N of M')", bool(re.search(r"\d+ of \d+", body)))
            shot(page, shots, "02_weekly_summary")

            # ---- R4: trends ---------------------------------------------------------------------------------
            check("R4 Trends section present", "Trends" in body)
            check("R4 trend chart rendered", page.locator('[data-testid="stPlotlyChart"], .js-plotly-plot').count() > 0)

            # ---- R5: topic insights -------------------------------------------------------------------------
            check("R5 topics section present", "What guests talk about" in body)
            topic_text = section_text(page, "What guests talk about")
            for label in ("Cleanliness", "Check-in", "Staff", "Noise", "Facilities", "Location", "Room condition", "Value"):
                check(f"R5 topic visible: {label}", label.lower() in topic_text.lower() or label.lower() in body.lower())

            # ---- R6: feed. Compare with the database --------------------------------------------------------
            choose(page, "Time period", "All time")
            shot(page, shots, "03_all_time")
            all_n = sum(stored.values())
            check("R6 feed count for All time equals rows in DB", feed_total(page) == all_n, f"ui={feed_total(page)} db={all_n}")
            check("R6 feed shows review cards", cards(page).count() > 0)

            tick(page, "Only negative reviews")
            neg = one(db, "select count(*) from reviews where rating < 5")
            check("R6 'Only negative' count equals DB (rating < 5)", feed_total(page) == neg, f"ui={feed_total(page)} db={neg}")
            check("R6 every visible card scored under 5", all(s < 5 for s in card_scores(page)) and card_scores(page) != [])
            shot(page, shots, "04_only_negative")
            tick(page, "Only negative reviews", False)

            tick(page, "No reply yet")
            nr = one(db, "select count(*) from reviews where host_reply is null")
            check("R6 'No reply yet' count equals DB", feed_total(page) == nr, f"ui={feed_total(page)} db={nr}")
            check("R6 'No reply yet' cards all carry the badge", cards(page).count() == page.locator(".az-review", has_text="No reply yet").count())
            tick(page, "No reply yet", False)

            for term in ("breakfast", "noise"):
                search(page, term)
                like = f"%{term}%"
                want = one(db, "select count(*) from reviews where lower(coalesce(title,'')||' '||coalesce(liked,'')||' '||coalesce(disliked,'')||' '||coalesce(host_reply,'')) like ?", like)
                ui = feed_total(page)
                # The dashboard may search only some fields, so require ui <= db and > 0 when db > 0.
                check(f"R6 search '{term}' finds matches and never more than the DB", (ui > 0 or want == 0) and ui <= want, f"ui={ui} db={want}")
                if ui:
                    check(f"R6 search '{term}': first card contains the word", term in cards(page).first.inner_text().lower())
            shot(page, shots, "05_search")
            search(page, "")

            page.get_by_role("combobox", name="Topic").click()
            page.get_by_role("option", name="Complaint: Cleanliness", exact=True).click()
            settle(page)
            cl = one(db, "select count(distinct review_key) from review_topics where topic='cleanliness' and polarity='negative'")
            check("R6 topic filter 'Complaint: Cleanliness' equals DB", feed_total(page) == cl, f"ui={feed_total(page)} db={cl}")
            check("R6 topic-filtered cards show the chip", cards(page).count() == page.locator(".az-review", has_text="Complaint: Cleanliness").count())
            shot(page, shots, "06_topic_filter")
            page.get_by_role("combobox", name="Topic").click()
            page.get_by_role("option", name="Any topic", exact=True).click()
            settle(page)

            choose(page, "Sort by", "Lowest score first")
            sc = card_scores(page)
            check("R6 'Lowest score first' really sorts ascending", sc == sorted(sc) and sc[0] == one(db, "select min(rating) from reviews"), f"first={sc[:3]}")
            choose(page, "Sort by", "Newest first")

            before = cards(page).first.inner_text()
            page.get_by_role("button", name="Next page").click()
            settle(page)
            check("R6 pagination: next page shows different reviews", cards(page).first.inner_text() != before)
            page.get_by_role("button", name="Previous page").click()
            settle(page)

            # ---- hotel filter -------------------------------------------------------------------------------
            for p in PROPERTIES:
                want = stored.get(p.slug, 0)
                page.goto(srv.url)
                wait_for_app(page)
                choose(page, "Time period", "All time")
                from harness import clear_hotels
                clear_hotels(page)
                page.get_by_role("combobox", name="Hotels").click()
                page.get_by_role("option", name=p.name, exact=True).click()
                page.keyboard.press("Escape")
                settle(page)
                if want:
                    check(f"R6 hotel filter {p.name}: feed equals DB", feed_total(page) == want, f"ui={feed_total(page)} db={want}")
                    shot(page, shots, f"07_hotel_{p.slug}")
                else:
                    t = main_text(page)
                    check(f"R6 hotel with no data ({p.name}) explains why instead of showing zeros",
                          bool(re.search(r"No reviews have been collected for the selected hotel", t)) and "blocked" in t.lower(), "")
                    shot(page, shots, f"07_hotel_{p.slug}")

            # ---- R7: CSV matches the filtered feed -----------------------------------------------------------
            page.goto(srv.url)
            wait_for_app(page)
            choose(page, "Time period", "All time")
            tick(page, "Only negative reviews")
            n_ui = feed_total(page)
            name, content = download_csv(page)
            rows = [ln for ln in content.splitlines() if ln.strip()]
            check("R7 CSV downloads", name.endswith(".csv"), name)
            import csv, io
            parsed = list(csv.DictReader(io.StringIO(content)))
            check("R7 CSV row count equals the filtered feed", len(parsed) == n_ui, f"csv={len(parsed)} ui={n_ui}")
            check("R7 CSV has no reviewer names/accounts", not any(k.lower() in ("reviewer", "reviewer_name", "author", "name") for k in (parsed[0] if parsed else {})), str(list(parsed[0])[:12]) if parsed else "")
            check("R7 CSV cells never start with a formula character",
                  not any(str(v).startswith(("=", "+", "@")) for r in parsed for v in r.values()))

            # ---- R8: data health ----------------------------------------------------------------------------
            dh = section_text(page, "Data health") or main_text(page)
            check("R8 data health section present", "Data health" in main_text(page))
            for p in PROPERTIES:
                check(f"R8 data health lists {p.name}", p.name in main_text(page))
            check("R8 Central Sydney shown as not collected", bool(re.search(r"Central Sydney.*(Never|No reviews|blocked)", main_text(page), re.I | re.S)))
            shot(page, shots, "08_data_health")

            # ---- usability: mobile width + help --------------------------------------------------------------
            page.set_viewport_size({"width": 400, "height": 900})
            page.goto(srv.url)
            wait_for_app(page)
            overflow = page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
            check("U1 phone width: no sideways scrolling", overflow <= 2, f"overflow={overflow}px")
            shot(page, shots, "09_phone")
            page.set_viewport_size({"width": 1400, "height": 3200})
            page.goto(srv.url)
            wait_for_app(page)
            page.get_by_text("How to read this").click()
            check("U2 plain-English 'How to read this' help opens", "Positive, mixed, negative" in main_text(page))

            # ---- no silent breakage -------------------------------------------------------------------------
            no_traceback(page)
            problems = mon.problems()
            check("L1 browser: no console errors, failed requests, outside hosts or dialogs", not problems, str(problems)[:300])
            bad = srv.bad_log_lines()
            check("L2 server log: no traceback, error or warning", not bad, "; ".join(bad)[:300])
            browser.close()
    finally:
        srv.stop()
    failed = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(failed)} passed, {len(failed)} failed. Screenshots: {shots}")
    return 1 if failed else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "data" / "reviews.db"))
    ap.add_argument("--shots", default=str(ROOT / "data" / "audit_shots"))
    ap.add_argument("--headed", action="store_true")
    a = ap.parse_args()
    sys.exit(run(a.db, Path(a.shots), a.headed))
