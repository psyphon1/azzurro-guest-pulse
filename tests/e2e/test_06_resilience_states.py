"""What staff see when the data is missing, empty, damaged, a snapshot or synthetic. Never a traceback, never a file path."""
import re

import pytest

from tests.e2e.harness import exception_boxes, main_text, no_traceback


def test_a_missing_database_gives_a_friendly_message_with_only_the_file_name(open_app, missing_server, e2e_folder):
    page, mon = open_app(missing_server)
    text = page.locator("body").inner_text()
    assert "No review data found" in text and "does_not_exist.db" in text
    assert str(e2e_folder) not in text and "/private/" not in text and "/tmp/" not in text      # no absolute path leaks
    no_traceback(page)
    mon.assert_clean()


def test_an_empty_database_explains_what_to_do(open_app, empty_server):
    page, mon = open_app(empty_server)
    assert "There are no reviews in the database yet" in page.locator("body").inner_text()
    no_traceback(page)
    mon.assert_clean()


def test_a_damaged_database_gives_a_friendly_message_and_no_internals(open_app, corrupt_server, e2e_folder):
    page, mon = open_app(corrupt_server)
    text = page.locator("body").inner_text()
    assert "could not be read" in text
    assert str(e2e_folder) not in text and "DatabaseError" not in text and "file is not a database" not in text
    no_traceback(page)
    mon.assert_clean()


def test_a_sample_snapshot_is_labelled_so_nobody_mistakes_it_for_live_data(open_app, sample_server):
    page, _ = open_app(sample_server)
    text = main_text(page)
    assert "SAMPLE DATA" in text and re.search(r"not live", text)


def test_synthetic_demo_data_is_labelled(open_app, demo_server):
    page, _ = open_app(demo_server)
    assert "DEMO DATA" in main_text(page)


def test_the_real_database_shows_neither_banner(open_app, main_server):
    page, _ = open_app(main_server)
    text = main_text(page)
    assert "SAMPLE DATA" not in text and "DEMO DATA" not in text


def test_the_data_file_caption_shows_only_a_file_name(open_app, main_server, e2e_folder):
    page, _ = open_app(main_server)
    side = page.locator('[data-testid="stSidebar"]').inner_text()
    assert "azzurro_reviews.db" in side and str(e2e_folder) not in side


def test_a_page_reload_comes_back_clean(open_app, main_server):
    page, mon = open_app(main_server)
    page.reload()
    page.wait_for_selector('[data-testid="stApp"]')
    page.get_by_role("heading", name="Review feed").wait_for()
    assert exception_boxes(page) == 0
    mon.assert_clean()


def test_a_url_with_junk_query_parameters_does_not_break_the_page(open_app, main_server):
    page, mon = open_app(main_server)
    page.goto(main_server.url + "/?props=%3Cscript%3E&range_preset=zzz&feed_search=" + "A" * 3000)
    page.get_by_role("heading", name="Review feed").wait_for()
    no_traceback(page)
    mon.assert_clean()


@pytest.mark.parametrize("path", ["/nonexistent-page", "/%00", "/../../etc/passwd", "/_stcore/stream"])
def test_odd_urls_do_not_expose_server_internals(main_server, path):
    import urllib.error
    import urllib.request
    try:
        with urllib.request.urlopen(main_server.url + path, timeout=10) as r:
            body = r.read(20000).decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        body = err.read(20000).decode("utf-8", "replace")
    except OSError:
        return                                                      # connection refused or reset is also acceptable
    assert "root:" not in body and "Traceback" not in body and "/Users/" not in body
