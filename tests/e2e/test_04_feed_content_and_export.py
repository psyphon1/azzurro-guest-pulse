"""What a single review looks like, and what leaves the building in the CSV."""
import csv
import io
import re

from tests.e2e.harness import card_scores, cards, choose, feed_total, main_text, settle, tick

ALL_TIME = "All time"


def test_a_review_card_shows_score_word_hotel_date_and_text_boxes(open_app, main_server):
    page, _ = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    first = cards(page).first
    text = first.inner_text()
    assert re.search(r"\d+(\.\d)?/10", text) and re.search(r"positive|mixed|negative", text, re.IGNORECASE)   # a word, not colour alone
    assert re.search(r"\b\w{3} \d{2} \w{3} \d{4}\b", text)
    assert any(h in text for h in ("Olympic Hotel Paddington", "Potts Point", "Darling Harbour"))
    assert page.locator(".az-liked").count() > 0 and page.locator(".az-disliked").count() > 0
    assert re.search("What guests liked", main_text(page), re.IGNORECASE) and re.search("What guests disliked", main_text(page), re.IGNORECASE)


def test_topic_chips_name_the_topic_in_words(open_app, main_server):
    page, _ = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    chips = page.locator(".az-chip").all_inner_texts()
    assert chips and all(re.match(r"(Complaint|Praise): ", c) for c in chips)


def test_reviewer_identity_is_never_on_screen(open_app, main_server):
    page, _ = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    feed_html = " ".join(page.locator(".az-review").evaluate_all("els => els.map(e => e.outerHTML)")).lower()
    for bad in ("username", "avatar", "reviewer name", "guest name", "<img"):
        assert bad not in feed_html, bad                           # no photo, no name, nothing that identifies a guest


def _download(page):
    from tests.e2e.harness import download_csv
    name, text = download_csv(page)
    return name, text.encode("utf-8")


def test_csv_download_matches_the_filters_and_is_a_valid_spreadsheet(open_app, main_server):
    page, mon = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    tick(page, "Only negative reviews")
    expected = feed_total(page)
    name, raw = _download(page)
    assert name == "azzurro_reviews.csv"
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    assert len(rows) == expected                                    # the file holds exactly what the feed says matched
    assert all(float(r["Score"]) < 5 for r in rows)
    assert {"Date", "Hotel", "Score", "What guests liked", "What guests disliked", "Hotel reply",
            "Complaint topics", "Praise topics"} <= set(rows[0])
    assert not [h for h in rows[0] if any(w in h.lower() for w in ("name", "avatar", "username", "email"))]
    mon.assert_clean()


def test_csv_cells_cannot_run_formulas_in_a_spreadsheet(open_app, main_server):
    page, _ = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    _, raw = _download(page)
    for row in csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))):
        for key, cell in row.items():
            assert not cell.lstrip().startswith(("=", "+", "@")), f"{key}: {cell[:40]!r}"
            assert not (cell.startswith("-") and not re.fullmatch(r"-?\d+(\.\d+)?", cell)), f"{key}: {cell[:40]!r}"


def test_csv_respects_the_hotel_filter(open_app, main_server):
    page, _ = open_app(main_server)
    from tests.e2e.harness import only_hotels
    choose(page, "Time period", ALL_TIME)
    only_hotels(page, ["Darling Harbour"])
    _, raw = _download(page)
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    assert rows and {r["Hotel"] for r in rows} == {"Darling Harbour"}
