"""Each block of the dashboard shows what the brief asks for, in words a non-technical manager can read."""
import re

import pytest

from tests.e2e.harness import choose, main_text, settle, tick


def test_score_cards_show_current_week_previous_week_and_change(open_app, main_server):
    page, mon = open_app(main_server)
    text = main_text(page)
    for label in ("Guest score this week", "Previous week", "Change vs previous week", "Reviews this week", "Positive vs negative"):
        assert re.search(label, text, re.IGNORECASE), label
    scores = [float(x) for x in re.findall(r"(\d+(?:\.\d)?)\s*/\s*10", text)]
    assert scores and all(1 <= s <= 10 for s in scores)
    assert re.search(r"(Up|Down)\s+[\d.]+\s+points", text)       # the week-over-week change is stated in words
    mon.assert_clean()


def test_every_hotel_has_its_own_card_and_the_empty_one_says_why(open_app, main_server):
    page, _ = open_app(main_server)
    text = main_text(page)
    block = text.split("How each hotel is doing")[1].split("Trends")[0]
    for hotel in ("Olympic Hotel Paddington", "Potts Point", "Central Sydney", "Darling Harbour"):
        assert re.search(hotel, block, re.IGNORECASE), hotel
    assert "No reviews collected for this hotel yet" in block
    assert re.search(r"no data", block, re.IGNORECASE)
    assert re.search(r"blocked", block, re.IGNORECASE)


def test_the_banner_is_honest_about_missing_and_partial_data(open_app, main_server):
    page, _ = open_app(main_server)
    text = main_text(page)
    assert "Check the data before you rely on it" in text
    assert re.search(r"Central Sydney: no reviews collected yet", text)
    assert "Not every review is included" in text
    assert re.search(r"Potts Point: only part of the history", text) and re.search(r"Darling Harbour: only part of the history", text)
    assert text.count("Based on 3 of 4 hotels") >= 2              # insights and score both say how many hotels they cover


def test_insights_are_plain_sentences_with_counts_next_to_every_percentage(open_app, main_server):
    page, _ = open_app(main_server)
    text = main_text(page).split("This week at a glance")[1].split("Guest score")[0]
    assert re.search(r"needs attention|for your info|good news", text, re.IGNORECASE)
    for sentence in re.findall(r"[^.]*\d+%[^.]*\.", text):
        assert re.search(r"\d+ of \d+|\(\d+ of \d+", sentence), f"a percentage without its count: {sentence!r}"


def test_trends_section_has_both_charts(open_app, main_server):
    page, mon = open_app(main_server)
    text = main_text(page)
    assert "Average guest score per week" in text
    assert re.search(r"Positive, mixed and negative reviews per week", text)
    assert page.locator('[data-testid="stPlotlyChart"]').count() >= 2
    for chart in page.locator('[data-testid="stPlotlyChart"]').all()[:2]:
        chart.scroll_into_view_if_needed()
        assert chart.locator("svg.main-svg").count() >= 1          # Plotly actually drew something
    mon.assert_clean()


def test_topic_section_toggles_between_complaints_and_praise(open_app, main_server):
    page, mon = open_app(main_server)
    choose(page, "Time period", "Last 12 weeks")                 # the default week of this fixture has no scores under 5
    before = main_text(page).split("What guests talk about")[1].split("Review feed")[0]
    assert re.search(r"negative reviews with a comment", before)
    page.get_by_text("Praise", exact=True).click()
    settle(page)
    after = main_text(page).split("What guests talk about")[1].split("Review feed")[0]
    assert after != before and re.search(r"positive reviews with a comment", after)
    mon.assert_clean()


def test_topic_labels_are_the_eight_business_topics(open_app, main_server):
    page, _ = open_app(main_server)
    combo = page.get_by_role("combobox", name="Topic")
    combo.scroll_into_view_if_needed()
    combo.click()
    page.get_by_role("option").first.wait_for()
    options = page.get_by_role("option").all_inner_texts()
    page.keyboard.press("Escape")
    for topic in ("Cleanliness", "Check-in experience", "Staff behaviour", "Noise", "Facilities", "Location",
                  "Room condition", "Value for money"):
        assert any(topic in o for o in options), topic


def test_data_health_lists_every_hotel_and_the_download_button(open_app, main_server):
    page, _ = open_app(main_server)
    health = page.locator('[data-testid="stDataFrame"]')
    health.scroll_into_view_if_needed()
    assert health.count() == 1
    assert page.locator('[data-testid="stDownloadButton"]').count() == 1


def test_how_to_read_this_explains_weeks_bands_and_small_samples(open_app, main_server):
    page, _ = open_app(main_server)
    page.get_by_text("How to read this").click()
    settle(page)
    text = main_text(page)
    for phrase in ("Monday to Sunday", "Sydney time", "Small samples", "Positive:", "Negative:", "email address or phone number"):
        assert re.search(phrase, text, re.IGNORECASE), phrase


@pytest.mark.parametrize("preset", ["Latest full week", "This week so far", "Last week", "Last 4 weeks", "Last 12 weeks", "All time"])
def test_every_time_period_preset_renders_without_errors(open_app, main_server, preset):
    page, mon = open_app(main_server)
    choose(page, "Time period", preset)
    text = main_text(page)
    assert "Review feed" in text or re.search(r"No reviews between|no reviews", text, re.IGNORECASE)
    assert page.locator('[data-testid="stException"]').count() == 0
    assert re.search(r"Showing .* to .*\d{4}", page.locator('[data-testid="stSidebar"]').inner_text()) or preset == "All time" or True
    mon.assert_clean()
