#!/usr/bin/env python3
"""Every report on the page vs numbers computed straight from data/reviews.db (SQL, not the dashboard's code)."""
import re, sqlite3
from datetime import date, timedelta, datetime
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright

DB = "data/reviews.db"
con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
q = lambda s, *a: con.execute(s, a).fetchall()
NAMES = {"olympic-paddington": "Olympic Hotel Paddington", "venus-potts-point-sydney": "Potts Point",
         "venus-surry-hills": "Central Sydney", "chateau-de-venus": "Darling Harbour"}
today = datetime.now(ZoneInfo("Australia/Sydney")).date()
mon = today - timedelta(days=today.weekday())
res = []
def check(name, ok, detail=""):
    res.append(ok); print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail else ""))

def kpi_values(p):
    cards = p.locator(".az-kpi").all_inner_texts()
    return {c.split("\n")[0]: c.split("\n")[1] for c in cards}

def hotel_cards(p):
    out = {}
    for c in p.locator(".az-hotel").all_inner_texts():
        lines = c.split("\n"); out[lines[0]] = c
    return out

def feed_total(p):
    m = re.search(r"(\d+) reviews? match", p.locator('[data-testid="stMain"]').inner_text())
    return int(m.group(1)) if m else -1

with sync_playwright() as pw:
    b = pw.chromium.launch(); p = b.new_page(viewport={"width": 1440, "height": 1400})
    p.goto("http://127.0.0.1:8501"); p.wait_for_selector(".az-kpi", timeout=60000); p.wait_for_timeout(2000)
    body = p.locator("body").inner_text()
    stored = dict(q("select property, count(*) from reviews group by 1"))
    check("data chip counts all 4 hotels now that Central Sydney has reviews", "Data: 4 of 4 hotels" in body,
          re.search(r"Data: \d of 4 hotels", body).group(0) if re.search(r"Data: \d of 4 hotels", body) else "")

    # ---- This week (default) ------------------------------------------------------------------------------------
    n, avg, neg = q("select count(*), round(avg(rating),1), sum(rating<5) from reviews where review_date between ? and ?",
                    mon.isoformat(), today.isoformat())[0]
    k = kpi_values(p)
    check("This week: Reviews KPI = DB", k.get("Reviews") == str(n), f"ui={k.get('Reviews')} db={n}")
    check("This week: Average score KPI = DB", n == 0 or k.get("Average score") == f"{avg:.1f}", f"ui={k.get('Average score')} db={avg}")
    check("This week: Negative % KPI = DB", n == 0 or k.get("Negative") == f"{round(100*neg/n)}%", f"ui={k.get('Negative')} db={round(100*neg/n) if n else None}%")
    un = q("select count(*) from reviews where rating<5 and (host_reply is null or trim(host_reply)='') and review_date >= ?",
           (today - timedelta(days=90)).isoformat())[0][0]
    check("Unanswered negatives (90 days) KPI = DB", k.get("Unanswered negatives") == str(un), f"ui={k.get('Unanswered negatives')} db={un}")
    cards = hotel_cards(p)
    for slug, name in NAMES.items():
        hn, havg = q("select count(*), round(avg(rating),1) from reviews where property=? and review_date between ? and ?",
                     slug, mon.isoformat(), today.isoformat())[0]
        c = cards.get(name, "")
        okn = f"{hn} review" in c
        oka = hn == 0 or f"{havg:.1f}" in c
        check(f"This week hotel card {name}: count and score = DB", bool(c) and okn and oka, f"db n={hn} avg={havg} | ui={c[:60]!r}")
    check("Central Sydney card is a real card, not 'No data'", "No data" not in cards.get("Central Sydney", "No data"))

    # ---- All time --------------------------------------------------------------------------------------------------
    p.locator('[data-testid="stButtonGroup"]').get_by_text("All time", exact=True).click(); p.wait_for_timeout(3500)
    total, tavg, tneg = q("select count(*), round(avg(rating),1), sum(rating<5) from reviews")[0]
    k = kpi_values(p)
    check("All time: Reviews KPI = every review in DB", k.get("Reviews") == str(total), f"ui={k.get('Reviews')} db={total}")
    check("All time: Average score KPI = DB", k.get("Average score") == f"{tavg:.1f}", f"ui={k.get('Average score')} db={tavg}")
    check("All time: Negative % KPI = DB", k.get("Negative") == f"{round(100*tneg/total)}%", f"ui={k.get('Negative')} db={round(100*tneg/total)}%")
    cards = hotel_cards(p)
    for slug, name in NAMES.items():
        hn, havg = q("select count(*), round(avg(rating),1) from reviews where property=?", slug)[0]
        c = cards.get(name, "")
        check(f"All time hotel card {name}: {hn} reviews, {havg} = DB", f"{hn} review" in c and f"{havg:.1f}" in c, c[:70].replace("\n", " "))
    check("All time: feed total = every review in DB", feed_total(p) == total, f"ui={feed_total(p)} db={total}")
    main = p.locator('[data-testid="stMain"]').inner_text()
    topics_part = main.split("Topics", 1)[1].split("Review feed", 1)[0] if "Topics" in main else ""
    check("Topics 'By hotel' includes Central Sydney", "Central Sydney" in topics_part)
    tc = q("select count(distinct t.review_key) from review_topics t join reviews r using(review_key) where r.property='venus-surry-hills'")[0][0]
    check("Central Sydney reviews carry topic tags in DB", tc > 0, f"{tc} tagged reviews")
    trend_txt = main.split("Trends", 1)[1].split("Topics", 1)[0] if "Trends" in main else ""
    check("Trends no longer says Central Sydney is excluded", "Not included" not in trend_txt or "Central Sydney" not in trend_txt)
    # Data health table
    p.get_by_text("Data health").first.scroll_into_view_if_needed(); p.wait_for_timeout(800)
    grid = p.locator('[data-testid="stDataFrame"]').last.inner_text()
    for slug, name in NAMES.items():
        pass
    # CSV download = feed
    with p.expect_download() as dl:
        p.get_by_role("button", name="Download these reviews as CSV").click()
    import csv, io
    rows = list(csv.DictReader(io.StringIO(open(dl.value.path(), encoding="utf-8-sig").read())))
    check("CSV download holds every review shown (All time)", len(rows) == total, f"csv={len(rows)} db={total}")
    check("CSV includes Central Sydney rows", any(r["Hotel"] == "Central Sydney" for r in rows))
    b.close()
print(f"\n{sum(res)} passed, {len(res)-sum(res)} failed")
