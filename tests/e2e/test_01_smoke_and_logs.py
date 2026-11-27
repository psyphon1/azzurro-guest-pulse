"""Does the app start, load cleanly and stay quiet? Everything the browser and the server say is inspected."""
import urllib.request

from tests.e2e.harness import exception_boxes, main_text

EXPECTED_HEADINGS = ["Filters", "Azzurro Hotels: guest review insights", "This week at a glance", "Guest score",
                     "How each hotel is doing", "Trends", "What guests talk about", "Review feed", "Data health"]


def test_server_reports_healthy(main_server):
    with urllib.request.urlopen(main_server.url + "/_stcore/health", timeout=5) as r:
        assert r.status == 200 and r.read().strip() == b"ok"


def test_page_loads_with_every_section_and_no_browser_problems(open_app, main_server):
    page, mon = open_app(main_server)
    assert page.get_by_role("heading").all_inner_texts() == EXPECTED_HEADINGS
    assert exception_boxes(page) == 0
    mon.assert_clean()                                            # console, page errors, failed/4xx requests, externals, dialogs
    assert mon.requests_seen > 20                                 # the monitor really was attached and saw traffic


def test_the_browser_only_talks_to_localhost(open_app, main_server):
    page, mon = open_app(main_server)
    assert mon.external_requests == []                            # no fonts, trackers or beacons from other hosts


def test_the_browser_tab_has_a_title(open_app, main_server):
    page, _ = open_app(main_server)
    assert page.title().strip() != ""


def test_hosting_chrome_is_hidden_from_staff(open_app, main_server):
    page, _ = open_app(main_server)
    assert page.get_by_role("button", name="Deploy").count() == 0   # toolbarMode = viewer in .streamlit/config.toml


def test_the_server_log_is_clean_after_loading(open_app, main_server):
    open_app(main_server)
    assert main_server.bad_log_lines() == []


def test_page_text_has_no_unrendered_placeholders(open_app, main_server):
    page, _ = open_app(main_server)
    text = main_text(page)
    for bad in ("nan", "NaN", "None", "undefined", "null", "{{", "}}", "[object"):
        assert bad not in text.split(), f"placeholder or raw value leaked into the page: {bad!r}"
    assert "NaN" not in text and "undefined" not in text and "[object" not in text
