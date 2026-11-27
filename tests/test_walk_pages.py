"""The paging loop, tested with fake 'browser' callables (no Playwright, no network)."""
import pytest

from scraper.browser import walk_pages
from scraper.errors import EndedEarlyError, FetchError
from scraper.models import ParsedPage


def make_page(sample_page, n, size=10, total=None):
    base = sample_page.reviews[0]
    return ParsedPage(reviews=[base.model_copy(update={"review_key": f"w{n}-{i}"}) for i in range(size)],
                      rejected=[], reported_total=total)


class FakeBrowser:
    """available_by_call[i] is what the 'Next page' button looks like at the i-th look."""
    def __init__(self, sample_page, pages, available_by_call, total):
        self.sample, self.total = sample_page, total
        self.pages = list(pages)            # sizes of the pages that clicking Next will deliver
        self.looks = list(available_by_call)
        self.clicks = 0
        self.waits = 0

    def next_available(self):
        return self.looks.pop(0) if self.looks else False

    def advance(self):
        size = self.pages.pop(0)
        self.clicks += 1
        return make_page(self.sample, self.clicks, size=size, total=self.total)

    def wait(self):
        self.waits += 1


def run(fb, first):
    return list(walk_pages(first, fb.next_available, fb.advance, fb.wait, lambda: None))


def test_walks_until_the_button_disappears_on_a_short_last_page(sample_page):
    fb = FakeBrowser(sample_page, pages=[10, 3], available_by_call=[True, True, False], total=23)

    pages = run(fb, make_page(sample_page, 0, total=23))

    assert [len(p.reviews) for p in pages] == [10, 10, 3]
    assert fb.waits == 0


def test_a_button_that_vanishes_midway_is_waited_for_and_found_again(sample_page):
    # Potts Point: button missing on the first look, back after a short wait
    fb = FakeBrowser(sample_page, pages=[10, 10], available_by_call=[False, True, True, False], total=30)

    pages = run(fb, make_page(sample_page, 0, total=30))

    assert len(pages) == 3 and fb.waits == 1


def test_a_button_that_never_comes_back_raises_ended_early_and_keeps_what_was_read(sample_page):
    fb = FakeBrowser(sample_page, pages=[10], available_by_call=[True] + [False] * 10, total=2386)
    seen = []

    with pytest.raises(EndedEarlyError) as err:
        for page in walk_pages(make_page(sample_page, 0, total=2386), fb.next_available, fb.advance, fb.wait, lambda: None):
            seen.append(page)

    assert len(seen) == 2                              # both pages were yielded before the error
    assert "20 of 2386" in str(err.value) and "throttl" in str(err.value).lower()


def test_endless_pages_hit_the_hard_ceiling(sample_page, monkeypatch):
    import scraper.browser as b
    monkeypatch.setattr(b, "MAX_PAGES", 5)
    fb = FakeBrowser(sample_page, pages=[10] * 50, available_by_call=[True] * 50, total=10**6)

    with pytest.raises(FetchError, match="ceiling"):
        run(fb, make_page(sample_page, 0, total=10**6))


def test_polite_delay_runs_before_every_click_but_not_before_the_first_page(sample_page):
    fb = FakeBrowser(sample_page, pages=[10, 3], available_by_call=[True, True, False], total=23)
    delays = []

    list(walk_pages(make_page(sample_page, 0, total=23), fb.next_available, fb.advance, fb.wait,
                    lambda: delays.append(1)))

    assert len(delays) == 2
