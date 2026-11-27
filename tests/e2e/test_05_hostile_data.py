"""A hostile guest writes attack code into every free-text field. The dashboard must show it as harmless text and
nothing must run, load from another host, hide the page, or leak contact details."""
import csv
import io
import re

from tests.e2e.dbs import XSS_PAYLOADS
from tests.e2e.harness import choose, exception_boxes, main_text, no_traceback


def _evil(open_app, evil_server):
    page, mon = open_app(evil_server)          # allow_external stays False: a beacon or iframe would be reported
    choose(page, "Time period", "All time")
    return page, mon


def test_no_injected_script_ever_runs(open_app, evil_server):
    page, mon = _evil(open_app, evil_server)
    ran = page.evaluate("Object.keys(window).filter(k => k.startsWith('__xss'))")
    assert ran == [], f"injected code executed: {ran}"
    assert mon.dialogs == []


def test_no_hostile_element_made_it_into_the_page(open_app, evil_server):
    page, _ = _evil(open_app, evil_server)
    assert page.locator('iframe[src*="attacker"]').count() == 0
    assert page.locator('img[src*="attacker"]').count() == 0
    assert page.locator('a[href^="javascript"]').count() == 0
    assert page.locator("[onerror], [onload]").count() == 0
    scripts = page.evaluate("Array.from(document.querySelectorAll('script')).map(s => s.textContent).join(' ')")
    assert "__xss" not in scripts


def test_no_request_is_sent_to_an_attacker_host(open_app, evil_server):
    page, mon = _evil(open_app, evil_server)
    assert mon.external_requests == []                              # tracking pixel and iframe payloads never loaded
    mon.assert_clean()


def test_a_style_payload_cannot_hide_or_restyle_the_page(open_app, evil_server):
    page, _ = _evil(open_app, evil_server)
    assert page.locator("body").evaluate("e => getComputedStyle(e).display") != "none"
    assert page.get_by_role("heading", name="Review feed").is_visible()
    assert page.locator('style:text("display:none !important")').count() == 0


def test_the_payload_is_shown_as_plain_text(open_app, evil_server):
    page, _ = _evil(open_app, evil_server)
    text = main_text(page)
    assert "window.__xss" in text                                   # visible as characters: proof it was escaped, not run


def test_contact_details_in_reviews_are_masked_on_screen(open_app, evil_server):
    from tests.e2e.harness import search
    page, _ = _evil(open_app, evil_server)
    search(page, "call")                                           # the review that carried a phone number
    text = main_text(page)
    assert "0412 345 678" not in text and "[phone removed]" in text
    search(page, "write to")                                       # ...and the one that carried an e-mail address
    text = main_text(page)
    assert "jo.smith@example.com" not in text and "***" in text


def test_a_hostile_scrape_error_is_shown_as_text_in_data_health_and_runs_nothing(open_app, evil_server):
    page, mon = _evil(open_app, evil_server)
    assert page.evaluate("typeof window.__xss_error") == "undefined"
    assert exception_boxes(page) == 0
    mon.assert_clean()


def test_the_csv_from_hostile_data_is_safe_to_open(open_app, evil_server):
    page, _ = _evil(open_app, evil_server)
    from tests.e2e.harness import download_csv
    _, raw = download_csv(page)
    assert "jo.smith@example.com" not in raw and "0412 345 678" not in raw
    for row in csv.DictReader(io.StringIO(raw)):
        for cell in row.values():
            assert not cell.lstrip().startswith(("=", "+", "@")), cell[:50]


def test_searching_for_a_hostile_string_does_not_execute_it(open_app, evil_server):
    from tests.e2e.harness import search
    page, _ = _evil(open_app, evil_server)
    search(page, "<script>")
    no_traceback(page)
    assert page.evaluate("Object.keys(window).filter(k => k.startsWith('__xss'))") == []


def test_every_payload_family_is_really_in_the_database(evil_server):
    import sqlite3
    con = sqlite3.connect(evil_server.db_path)
    blob = " ".join(str(x) for row in con.execute("select title, liked, disliked, host_reply from reviews") for x in row)
    for name, payload in XSS_PAYLOADS.items():
        assert payload[:12] in blob, f"fixture does not contain the {name} payload: the tests above would prove nothing"
