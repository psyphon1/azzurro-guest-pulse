"""The Potts Point lesson: a missing 'Next page' button is NOT proof that the reviews ended."""
import pytest

from scraper.pagination import MAX_RETRIES, next_step


def step(**kw):
    base = dict(last_page_size=10, collected=100, reported_total=1000, next_available=False, retries_used=0)
    base.update(kw)
    return next_step(**base)


def test_next_button_available_means_keep_going():
    assert step(next_available=True) == "continue"


def test_short_last_page_is_a_real_end():
    assert step(last_page_size=3, collected=133, reported_total=133) == "end"   # Olympic: 14th page had 3 reviews


def test_full_last_page_but_we_hold_what_booking_reports_is_a_real_end():
    assert step(last_page_size=10, collected=130, reported_total=133) == "end"   # within 10%


def test_full_page_but_far_short_of_the_total_is_suspicious_so_retry_first():
    # Potts Point: 144 full pages = 1,440 of 2,386 reported, then the button vanished
    assert step(collected=1440, reported_total=2386, retries_used=0) == "retry"


def test_retries_are_limited_then_it_is_reported_as_ended_early():
    assert step(collected=1440, reported_total=2386, retries_used=MAX_RETRIES) == "ended_early"


def test_without_a_reported_total_a_full_page_is_trusted_as_the_end():
    assert step(collected=1440, reported_total=None) == "end"       # nothing to compare against


@pytest.mark.parametrize("bad", [0, -5])
def test_nonsense_reported_total_is_ignored(bad):
    assert step(collected=1440, reported_total=bad) == "end"


def test_an_empty_last_page_is_an_end():
    assert step(last_page_size=0, collected=50, reported_total=1000) == "end"
