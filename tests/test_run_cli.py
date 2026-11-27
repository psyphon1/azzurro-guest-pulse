import pytest

from scraper import run as run_module
from scraper.models import ParsedPage


def fake_fetcher(sample_page, total):
    def fetch(url, slug, **kw):
        n = 0
        while n < 500:  # a huge site: only the cap should stop us (500 is a test-safety valve, not the cap)
            base = sample_page.reviews[0]
            yield ParsedPage(reviews=[base.model_copy(update={"review_key": f"{slug}-{n}-{i}"}) for i in range(10)],
                             rejected=[], reported_total=total)
            n += 1
    return fetch


def test_cli_applies_the_page_cap_and_says_so(tmp_path, sample_page, monkeypatch, capsys):
    monkeypatch.setattr(run_module, "fetch_pages", fake_fetcher(sample_page, total=3000))

    code = run_module.main(["--property", "chateau-de-venus", "--mode", "full", "--max-pages", "4",
                            "--db", str(tmp_path / "t.db")])

    out = capsys.readouterr().out
    assert code == 0                       # hitting the cap on purpose is not a failure
    assert "TRUNCATED" in out
    assert "newest 40 of 3000" in out
    assert "4-page limit" in out


def test_cli_default_cap_is_200_pages(tmp_path, sample_page, monkeypatch):
    monkeypatch.setattr(run_module, "fetch_pages", fake_fetcher(sample_page, total=99999))

    run_module.main(["--property", "chateau-de-venus", "--mode", "full", "--no-date-window",
                     "--db", str(tmp_path / "t.db")])

    import sqlite3
    row = sqlite3.connect(str(tmp_path / "t.db")).execute("select pages, max_pages, truncated from scrape_runs").fetchone()
    assert row == (200, 200, 1)


@pytest.mark.parametrize("bad", ["0", "-5", "abc"])
def test_cli_rejects_nonsense_page_caps(bad, tmp_path, capsys):
    with pytest.raises(SystemExit):
        run_module.main(["--max-pages", bad, "--db", str(tmp_path / "t.db")])
    assert "positive whole number" in capsys.readouterr().err


# ---------------------------------------------------------------- date window, pauses, retry (Phase A2)
from datetime import date, timedelta  # noqa: E402

from scraper.errors import BlockedError  # noqa: E402


def dated_fetcher(sample_page, total=5000):
    """Reviews get 2 days older per review: 20 days per page."""
    def fetch(url, slug, **kw):
        n = 0
        while n < 500:
            base = sample_page.reviews[0]
            yield ParsedPage(reviews=[base.model_copy(update={"review_key": f"{slug}-{n}-{i}",
                                                              "review_date": date(2026, 11, 27) - timedelta(days=2 * (n * 10 + i))})
                                      for i in range(10)], rejected=[], reported_total=total)
            n += 1
    return fetch


@pytest.fixture
def fixed_today(monkeypatch):
    monkeypatch.setattr(run_module, "_today", lambda: date(2026, 11, 27))


def test_cli_default_window_is_365_days_and_says_so(tmp_path, sample_page, monkeypatch, capsys, fixed_today):
    monkeypatch.setattr(run_module, "fetch_pages", dated_fetcher(sample_page))

    code = run_module.main(["--property", "chateau-de-venus", "--mode", "full", "--db", str(tmp_path / "t.db")])

    out = capsys.readouterr().out
    assert code == 0
    assert "stop=date_window" in out
    assert "last 365 days" in out
    import sqlite3
    pages, since = sqlite3.connect(str(tmp_path / "t.db")).execute("select pages, since_days from scrape_runs").fetchone()
    assert since == 365 and pages == 20              # 20 days per page: page 19 (380 days back) is the first wholly outside 365


def test_cli_window_can_be_shortened_or_disabled(tmp_path, sample_page, monkeypatch, capsys, fixed_today):
    monkeypatch.setattr(run_module, "fetch_pages", dated_fetcher(sample_page))
    run_module.main(["--property", "chateau-de-venus", "--mode", "full", "--since-days", "30", "--db", str(tmp_path / "a.db")])
    assert "last 30 days" in capsys.readouterr().out

    run_module.main(["--property", "chateau-de-venus", "--mode", "full", "--no-date-window", "--max-pages", "5",
                     "--db", str(tmp_path / "b.db")])
    assert "stop=page_cap" in capsys.readouterr().out


@pytest.mark.parametrize("bad", ["0", "-1", "x"])
def test_cli_rejects_nonsense_windows(bad, tmp_path, capsys):
    with pytest.raises(SystemExit):
        run_module.main(["--since-days", bad, "--db", str(tmp_path / "t.db")])
    assert "positive whole number" in capsys.readouterr().err


def finite_fetcher(sample_page, pages=2):
    def fetch(url, slug, **kw):
        base = sample_page.reviews[0]
        for n in range(pages):
            yield ParsedPage(reviews=[base.model_copy(update={"review_key": f"{slug}-{n}-{i}"}) for i in range(10)],
                             rejected=[], reported_total=pages * 10)
    return fetch


def test_cli_pauses_between_hotels_but_not_before_the_first_or_after_the_last(tmp_path, sample_page, monkeypatch, fixed_today):
    monkeypatch.setattr(run_module, "fetch_pages", finite_fetcher(sample_page))
    sleeps = []
    monkeypatch.setattr(run_module, "_sleep", sleeps.append)

    run_module.main(["--property", "all", "--mode", "full", "--no-date-window", "--pause", "60", "--db", str(tmp_path / "t.db")])

    assert len(sleeps) == 3                                   # 4 hotels -> 3 gaps
    assert all(60 <= s <= 120 for s in sleeps)


def test_cli_pause_zero_disables_pauses(tmp_path, sample_page, monkeypatch, fixed_today):
    monkeypatch.setattr(run_module, "fetch_pages", finite_fetcher(sample_page))
    sleeps = []
    monkeypatch.setattr(run_module, "_sleep", sleeps.append)

    run_module.main(["--property", "all", "--mode", "full", "--no-date-window", "--pause", "0", "--db", str(tmp_path / "t.db")])

    assert sleeps == []


def test_a_blocked_hotel_is_retried_once_after_a_long_back_off(tmp_path, sample_page, monkeypatch, capsys, fixed_today):
    calls = {"n": 0}
    good = finite_fetcher(sample_page)

    def flaky(url, slug, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise BlockedError("Bot check did not clear")
            yield  # pragma: no cover  (makes this a generator)
        yield from good(url, slug)

    monkeypatch.setattr(run_module, "fetch_pages", flaky)
    sleeps = []
    monkeypatch.setattr(run_module, "_sleep", sleeps.append)

    code = run_module.main(["--property", "venus-surry-hills", "--mode", "full", "--no-date-window",
                            "--pause", "0", "--db", str(tmp_path / "t.db")])

    out = capsys.readouterr().out
    assert code == 0                                         # recovered
    assert calls["n"] == 2
    assert sleeps and sleeps[0] >= run_module.BLOCK_BACKOFF_S
    assert "blocked" in out and "retrying" in out
    import sqlite3
    statuses = [r[0] for r in sqlite3.connect(str(tmp_path / "t.db")).execute("select status from scrape_runs order by id")]
    assert statuses == ["blocked", "ok"]                     # both attempts are on the record


def test_a_hotel_that_stays_blocked_is_retried_only_once_then_reported(tmp_path, sample_page, monkeypatch, capsys, fixed_today):
    calls = {"n": 0}

    def always_blocked(url, slug, **kw):
        calls["n"] += 1
        raise BlockedError("Bot check did not clear")
        yield  # pragma: no cover

    monkeypatch.setattr(run_module, "fetch_pages", always_blocked)
    monkeypatch.setattr(run_module, "_sleep", lambda s: None)

    code = run_module.main(["--property", "venus-surry-hills", "--mode", "full", "--pause", "0", "--db", str(tmp_path / "t.db")])

    assert code == 1 and calls["n"] == 2
    assert "try again later" in capsys.readouterr().out.lower()
