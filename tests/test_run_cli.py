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

    run_module.main(["--property", "chateau-de-venus", "--mode", "full", "--db", str(tmp_path / "t.db")])

    import sqlite3
    row = sqlite3.connect(str(tmp_path / "t.db")).execute("select pages, max_pages, truncated from scrape_runs").fetchone()
    assert row == (200, 200, 1)


@pytest.mark.parametrize("bad", ["0", "-5", "abc"])
def test_cli_rejects_nonsense_page_caps(bad, tmp_path, capsys):
    with pytest.raises(SystemExit):
        run_module.main(["--max-pages", bad, "--db", str(tmp_path / "t.db")])
    assert "positive whole number" in capsys.readouterr().err
