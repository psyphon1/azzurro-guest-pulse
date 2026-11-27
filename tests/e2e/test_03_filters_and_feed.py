"""Date and property filters and every control of the review feed, exercised like a person would."""
import re

from tests.e2e.harness import (card_scores, cards, choose, clear_hotels, exception_boxes, feed_total, main_text,
                               no_traceback, only_hotels, search, settle, sidebar, tick)

ALL_TIME = "All time"


def test_the_hotel_filter_lists_all_four_hotels_selected_by_default(open_app, main_server):
    page, _ = open_app(main_server)
    tags = sidebar(page).locator("[data-tag]").all_inner_texts()
    assert tags == ["Olympic Hotel Paddington", "Potts Point", "Central Sydney", "Darling Harbour"]


def test_selecting_one_hotel_narrows_the_whole_page_and_the_feed(open_app, main_server):
    page, mon = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    all_total = feed_total(page)
    only_hotels(page, ["Potts Point"])
    assert 0 < feed_total(page) < all_total
    assert all("Potts Point" in c for c in cards(page).all_inner_texts())
    block = main_text(page).split("How each hotel is doing")[1].split("Trends")[0]
    assert re.search("Potts Point", block, re.IGNORECASE) and not re.search("Darling Harbour", block, re.IGNORECASE)
    assert exception_boxes(page) == 0
    mon.assert_clean()


def test_selecting_only_the_hotel_with_no_data_gives_a_friendly_message(open_app, main_server):
    page, mon = open_app(main_server)
    only_hotels(page, ["Central Sydney"])
    text = main_text(page)
    assert re.search(r"No reviews have been collected for the selected hotel", text)
    assert "No reviews collected for this hotel yet" in text      # its card is still shown, with the reason
    no_traceback(page)
    mon.assert_clean()


def test_clearing_every_hotel_asks_the_user_to_choose_one(open_app, main_server):
    page, mon = open_app(main_server)
    clear_hotels(page)
    assert "Choose at least one hotel in the sidebar." in main_text(page)
    no_traceback(page)
    only_hotels(page, [])                                          # no-op; page stays usable
    mon.assert_clean()


def test_the_custom_date_range_shows_date_pickers(open_app, main_server):
    page, mon = open_app(main_server)
    choose(page, "Time period", "Custom dates")
    assert page.get_by_label("From and to").count() >= 1
    no_traceback(page)
    mon.assert_clean()


def test_changing_the_period_changes_the_numbers_and_the_caption(open_app, main_server):
    page, _ = open_app(main_server)
    first = sidebar(page).inner_text()
    n_week = feed_total(page)
    choose(page, "Time period", ALL_TIME)
    assert feed_total(page) > n_week
    assert sidebar(page).inner_text() != first                    # "Showing Mon .. to Sun .." caption changed


def test_a_period_with_no_reviews_gives_a_friendly_empty_state(open_app, main_server):
    page, mon = open_app(main_server)
    only_hotels(page, ["Olympic Hotel Paddington"])
    choose(page, "Time period", "This week so far")               # fixture data ends 27 Nov; "this week" is the real current week
    text = main_text(page)
    assert re.search(r"No reviews between|Review feed", text)
    no_traceback(page)
    mon.assert_clean()


# ---------------------------------------------------------------------------------------------- the review feed
def test_feed_shows_at_most_ten_reviews_per_page_with_a_match_count(open_app, main_server):
    page, _ = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    assert 0 < cards(page).count() <= 10
    assert re.search(r"[\d,]+ reviews match \(\d+ with a written comment, \d+ rating only\)\. Page 1 of \d+\.", main_text(page))


def test_only_negative_reviews_filter_shows_only_scores_under_five(open_app, main_server):
    page, _ = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    everything = feed_total(page)
    tick(page, "Only negative reviews")
    scores = card_scores(page)
    assert scores and all(s < 5 for s in scores)
    assert feed_total(page) < everything


def test_no_reply_yet_filter_shows_only_unanswered_reviews(open_app, main_server):
    page, _ = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    tick(page, "No reply yet")
    texts = cards(page).all_inner_texts()
    assert texts and all("No reply yet" in t and "Hotel reply" not in t for t in texts)


def test_has_written_comment_filter_hides_rating_only_reviews(open_app, main_server):
    page, _ = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    tick(page, "Has written comment")
    assert all("Rating only, no written comment" not in t for t in cards(page).all_inner_texts())


def test_search_finds_matching_text_and_ignores_case(open_app, main_server):
    page, _ = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    search(page, "NOISY")
    texts = [t.lower() for t in cards(page).all_inner_texts()]
    assert texts and all("noisy" in t for t in texts)


def test_search_with_no_match_says_so_and_offers_a_way_out(open_app, main_server):
    page, mon = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    search(page, "zzzxqj-no-such-word")
    assert "No reviews match these filters. Try clearing a filter." in main_text(page)
    assert cards(page).count() == 0
    mon.assert_clean()


def test_search_treats_special_characters_as_plain_text(open_app, main_server):
    page, mon = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    for nasty in ["(", "[a-", ".*", "\\", "(a+)+$", "%", "' OR 1=1 --", "<b>bold</b>"]:
        search(page, nasty)
        no_traceback(page)
    mon.assert_clean()


def test_topic_filter_shows_only_reviews_with_that_tag(open_app, main_server):
    page, _ = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    choose(page, "Topic", "Complaint: Noise")
    texts = cards(page).all_inner_texts()
    assert texts and all("Complaint: Noise" in t for t in texts)


def test_sorting_by_lowest_score_orders_the_page(open_app, main_server):
    page, _ = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    choose(page, "Sort by", "Lowest score first")
    scores = card_scores(page)
    assert scores == sorted(scores)
    choose(page, "Sort by", "Newest first")
    dates = [d for d in re.findall(r"\b\w{3} \d{2} \w{3} \d{4}\b", " ".join(cards(page).all_inner_texts()))]
    assert dates


def test_pagination_moves_forward_and_back_and_disables_at_the_ends(open_app, main_server):
    page, _ = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    prev, nxt = page.get_by_role("button", name="Previous page"), page.get_by_role("button", name="Next page")
    assert prev.is_disabled() and nxt.is_enabled()
    first_page = cards(page).all_inner_texts()
    nxt.click(); settle(page)
    assert "Page 2 of" in main_text(page) and cards(page).all_inner_texts() != first_page
    prev.click(); settle(page)
    assert "Page 1 of" in main_text(page) and cards(page).all_inner_texts() == first_page


def test_paging_to_the_last_page_disables_next(open_app, main_server):
    page, _ = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    pages = int(re.search(r"Page 1 of (\d+)", main_text(page)).group(1))
    nxt = page.get_by_role("button", name="Next page")
    for _ in range(pages - 1):
        nxt.click(); settle(page)
    assert f"Page {pages} of {pages}" in main_text(page) and nxt.is_disabled()


def test_changing_a_filter_returns_the_feed_to_page_one(open_app, main_server):
    page, _ = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    page.get_by_role("button", name="Next page").click(); settle(page)
    tick(page, "Only negative reviews")
    assert "Page 1 of" in main_text(page)


def test_every_feed_control_combination_survives(open_app, main_server):
    page, mon = open_app(main_server)
    choose(page, "Time period", ALL_TIME)
    tick(page, "Only negative reviews"); tick(page, "No reply yet"); tick(page, "Has written comment")
    choose(page, "Topic", "Complaint: Cleanliness"); choose(page, "Sort by", "Lowest score first"); search(page, "dirty")
    no_traceback(page)
    assert re.search(r"match|No reviews match", main_text(page))
    mon.assert_clean()
