"""Public-demo mode of the dashboard: database resolution, the SAMPLE DATA banner, and the hosted dependency set.

Nothing here touches data/reviews.db, data/demo.db or the network. Every test builds its own files in tmp_path and
points `dashboard.ui.data.ROOT` (the project root used for the default locations) at that folder.
"""
import ast
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dashboard.ui import data as D  # noqa: E402
from tests.test_dashboard_smoke import APP, build_db, page_text  # noqa: E402

BANNER_START = "SAMPLE DATA: a snapshot of real public Booking.com reviews, not live. Collected on "


@pytest.fixture
def fake_root(tmp_path, monkeypatch):
    """A project root of its own: the real data/ folder is never consulted."""
    root = tmp_path / "project"
    (root / "data").mkdir(parents=True)
    monkeypatch.setattr(D, "ROOT", root)
    monkeypatch.delenv("REVIEWS_DB", raising=False)
    return root


def sample_path(root: Path) -> Path:
    return root / "data" / "sample" / "reviews_sample.db"


def make_sample(root: Path) -> Path:
    (root / "data" / "sample").mkdir(parents=True, exist_ok=True)
    return build_db(sample_path(root))


def run(monkeypatch=None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    return at


# --- resolution order ---------------------------------------------------------------------------
def test_env_var_wins_over_both_default_files(fake_root, monkeypatch, tmp_path):
    (fake_root / "data" / "reviews.db").write_bytes(b"x")
    make_sample(fake_root)
    chosen = tmp_path / "mine.db"
    chosen.write_bytes(b"x")
    monkeypatch.setenv("REVIEWS_DB", str(chosen))
    assert D.resolve_db_path() == chosen


def test_env_var_pointing_at_a_missing_file_is_still_honoured_not_replaced_by_the_sample(fake_root, monkeypatch, tmp_path):
    make_sample(fake_root)
    monkeypatch.setenv("REVIEWS_DB", str(tmp_path / "typo.db"))
    assert D.resolve_db_path() == tmp_path / "typo.db"


def test_live_database_is_preferred_over_the_sample(fake_root):
    live = fake_root / "data" / "reviews.db"
    live.write_bytes(b"x")
    make_sample(fake_root)
    assert D.resolve_db_path() == live


def test_sample_is_used_when_there_is_no_live_database(fake_root):
    s = make_sample(fake_root)
    assert D.resolve_db_path() == s


def test_nothing_found_returns_the_live_default_so_the_no_data_message_names_it(fake_root):
    p = D.resolve_db_path()
    assert p == fake_root / "data" / "reviews.db" and not p.exists()


def test_default_locations_do_not_depend_on_the_working_directory(fake_root, monkeypatch, tmp_path):
    s = make_sample(fake_root)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert D.resolve_db_path() == s


def test_a_sample_in_the_working_directory_is_not_picked_up_instead_of_the_project_one(fake_root, monkeypatch, tmp_path):
    """Only the project root counts: a planted data/sample/ in whatever folder the server started in is ignored."""
    other = tmp_path / "cwd"
    (other / "data" / "sample").mkdir(parents=True)
    (other / "data" / "sample" / "reviews_sample.db").write_bytes(b"planted")
    monkeypatch.chdir(other)
    assert D.resolve_db_path() == fake_root / "data" / "reviews.db"


@pytest.mark.parametrize("raw", ["", "   "])
def test_blank_env_var_counts_as_not_set(fake_root, monkeypatch, raw):
    s = make_sample(fake_root)
    monkeypatch.setenv("REVIEWS_DB", raw)
    assert D.resolve_db_path() == s


def test_a_directory_named_reviews_db_is_not_chosen_as_the_live_file(fake_root):
    (fake_root / "data" / "reviews.db").mkdir()
    s = make_sample(fake_root)
    assert D.resolve_db_path() == s


# --- is this a snapshot? ------------------------------------------------------------------------
@pytest.mark.parametrize("name,expected", [("reviews_sample.db", True), ("My_SAMPLE.db", True), ("reviews.db", False),
                                           ("azzurro_demo.db", False)])
def test_is_sample_looks_at_the_file_name(tmp_path, name, expected):
    assert D.is_sample(tmp_path / name) is expected


def test_a_symlink_with_an_innocent_name_to_the_sample_still_counts_as_sample(tmp_path):
    """Staff must never mistake a snapshot for live data, whatever the link is called."""
    real = tmp_path / "reviews_sample.db"
    real.write_bytes(b"x")
    link = tmp_path / "reviews.db"
    link.symlink_to(real)
    assert D.is_sample(link) is True


# --- the banner text ----------------------------------------------------------------------------
def test_banner_text_uses_the_last_successful_scrape_date(tmp_path):
    import insights.metrics as m
    db = build_db(tmp_path / "reviews_sample.db")
    text = D.sample_banner_text(m.data_health(db))
    assert text == BANNER_START + "27 Nov 2026."


def test_banner_text_says_unknown_when_there_is_no_scrape_history():
    import pandas as pd
    empty = pd.DataFrame({"last_ok_at": [pd.NaT, pd.NaT]})
    assert D.sample_banner_text(empty) == BANNER_START + "unknown."
    assert D.sample_banner_text(None) == BANNER_START + "unknown."
    assert D.sample_banner_text(pd.DataFrame()) == BANNER_START + "unknown."


# --- the whole app ------------------------------------------------------------------------------
def test_app_shows_the_sample_banner_when_it_falls_back_to_the_snapshot(fake_root):
    make_sample(fake_root)
    at = run()
    assert not at.exception and not at.error
    text = page_text(at)
    assert BANNER_START + "27 Nov 2026." in text
    assert "Data file: reviews_sample.db" in text
    assert "Review feed" in text


def test_app_shows_no_sample_banner_for_the_live_database(fake_root):
    build_db(fake_root / "data" / "reviews.db")
    make_sample(fake_root)
    at = run()
    assert not at.exception
    text = page_text(at)
    assert "SAMPLE DATA" not in text
    assert "Data file: reviews.db" in text


def test_app_shows_sample_banner_when_env_var_names_a_sample_file(fake_root, monkeypatch, tmp_path):
    db = build_db(tmp_path / "other_sample.db")
    monkeypatch.setenv("REVIEWS_DB", str(db))
    assert "SAMPLE DATA: a snapshot of real public" in page_text(run())


def test_app_keeps_the_demo_banner_and_does_not_call_demo_data_a_sample(monkeypatch, tmp_path):
    db = build_db(tmp_path / "azzurro_demo.db")
    monkeypatch.setenv("REVIEWS_DB", str(db))
    text = page_text(run())
    assert "DEMO DATA: synthetic, not real guest reviews" in text
    assert "SAMPLE DATA" not in text


def test_app_sample_without_scrape_history_says_unknown(fake_root):
    s = make_sample(fake_root)
    con = sqlite3.connect(s)
    con.execute("DELETE FROM scrape_runs")
    con.commit()
    con.close()
    at = run()
    assert not at.exception
    assert BANNER_START + "unknown." in page_text(at)


def test_app_with_neither_file_shows_the_friendly_no_data_message_and_no_path(fake_root):
    at = run()
    assert not at.exception and not at.error
    text = page_text(at)
    assert "No review data found" in text and "reviews.db" in text
    assert str(fake_root) not in text and "SAMPLE DATA" not in text


def test_hostile_scrape_run_timestamp_cannot_inject_markup_into_the_banner(fake_root):
    s = make_sample(fake_root)
    con = sqlite3.connect(s)
    con.execute("UPDATE scrape_runs SET finished_at = '<img src=x onerror=alert(1)>', started_at = '<b>x</b>'")
    con.commit()
    con.close()
    at = run()
    assert not at.exception
    banner = [e.value for e in at.markdown if "SAMPLE DATA" in str(e.value)]
    assert banner and "<img" not in banner[0] and "<b>" not in banner[0]
    assert BANNER_START + "unknown." in banner[0]


# --- break the resolution logic (regression guards) --------------------------------------------
def test_symlink_with_a_live_looking_name_to_the_sample_still_gets_the_sample_banner(fake_root):
    real = make_sample(fake_root)
    link = fake_root / "data" / "reviews.db"
    link.symlink_to(real)
    at = run()
    assert not at.exception
    assert "SAMPLE DATA: a snapshot of real public" in page_text(at)


def test_reviews_db_pointing_at_a_directory_is_a_friendly_message_and_does_not_fall_back_to_the_sample(fake_root, monkeypatch, tmp_path):
    make_sample(fake_root)
    d = tmp_path / "adir.db"
    d.mkdir()
    monkeypatch.setenv("REVIEWS_DB", str(d))
    at = run()
    assert not at.exception
    text = page_text(at)
    assert "SAMPLE DATA" not in text and str(tmp_path) not in text
    assert "could not be read" in text or "No review data found" in text


def test_empty_live_file_is_reported_not_silently_replaced_by_the_sample(fake_root):
    (fake_root / "data" / "reviews.db").write_bytes(b"")
    make_sample(fake_root)
    at = run()
    assert not at.exception
    text = page_text(at)
    assert "SAMPLE DATA" not in text and "Data file: reviews_sample.db" not in text
    assert "could not be read" in text or "no reviews in the database yet" in text


def test_corrupt_sample_gives_the_friendly_message(fake_root):
    s = sample_path(fake_root)
    s.parent.mkdir(parents=True)
    s.write_bytes(b"this is not sqlite " * 500)
    at = run()
    assert not at.exception
    text = page_text(at)
    assert "could not be read" in text
    assert "Traceback" not in text and str(fake_root) not in text


def test_env_path_with_uri_parameters_cannot_open_read_write_or_create_a_file(fake_root, monkeypatch, tmp_path):
    monkeypatch.setenv("REVIEWS_DB", str(tmp_path / "ghost_sample.db") + "?mode=rwc")
    at = run()
    assert not at.exception
    assert sorted(p.name for p in tmp_path.iterdir()) == ["project"]      # nothing created next to it


def test_running_the_app_on_the_sample_never_modifies_it(fake_root):
    s = make_sample(fake_root)
    before = (s.read_bytes(), s.stat().st_mtime_ns)
    run()
    assert (s.read_bytes(), s.stat().st_mtime_ns) == before
    assert sorted(p.name for p in s.parent.iterdir()) == ["reviews_sample.db"]    # no -wal, -shm or -journal


# --- hosted build: only the packages in dashboard/requirements.txt --------------------------------
LOCAL = {"dashboard", "insights", "scraper", "scripts", "tests"}
ALLOWED = {"streamlit", "pandas", "plotly", "pydantic"}


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):                       # includes imports inside functions and try blocks
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def _module_file(name: str) -> Path | None:
    p = ROOT.joinpath(*name.split("."))
    if p.with_suffix(".py").is_file():
        return p.with_suffix(".py")
    if (p / "__init__.py").is_file():
        return p / "__init__.py"
    return None


def dashboard_import_closure() -> tuple[set[str], set[str]]:
    """(project modules reached from dashboard/app.py, third-party top-level packages they import)."""
    todo, seen, third = [str(Path(APP).relative_to(ROOT).with_suffix("")).replace(os.sep, ".")], set(), set()
    while todo:
        mod = todo.pop()
        f = _module_file(mod)
        if mod in seen or f is None:
            continue
        seen.add(mod)
        parts = mod.split(".")
        for i in range(1, len(parts)):                # importing a.b.c runs a and a.b first
            todo.append(".".join(parts[:i]))
        for imp in _imports_of(f):
            top = imp.split(".")[0]
            if top in LOCAL:
                todo.append(imp)
            elif top not in sys.stdlib_module_names and top != "__future__":
                third.add(top)
    return seen, third


def test_the_dashboard_imports_nothing_outside_the_hosted_requirements():
    seen, third = dashboard_import_closure()
    assert {"dashboard.app", "dashboard.ui.sections", "insights.metrics", "scraper.config"} <= seen
    assert third <= ALLOWED, f"the dashboard would break on a host that installs only {ALLOWED}: {third - ALLOWED}"
    assert not any(m.startswith(("scripts", "tests")) for m in seen)


def test_the_dashboard_never_imports_the_browser_automation_or_the_scraper_runtime():
    seen, third = dashboard_import_closure()
    assert "playwright" not in third and "pytest" not in third
    assert not {m for m in seen if m.startswith("scraper.") and m not in ("scraper.config",)}, \
        "the dashboard should only need scraper.config from the scraper package"


def test_the_dashboard_modules_import_with_playwright_and_pytest_blocked():
    code = (
        "import sys\n"
        "for name in ('playwright', 'pytest', '_pytest'):\n"
        "    sys.modules[name] = None\n"            # None in sys.modules makes `import name` raise ImportError
        "sys.path.insert(0, sys.argv[1])\n"
        "import dashboard.ui.data, dashboard.ui.sections, insights.metrics, insights.topics, scraper.config\n"
        "print('ok')\n"
    )
    out = subprocess.run([sys.executable, "-c", code, str(ROOT)], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0 and out.stdout.strip() == "ok", out.stderr[-800:]


def test_dashboard_requirements_file_lists_only_the_runtime_packages_with_ranges():
    lines = [ln.strip() for ln in (ROOT / "dashboard" / "requirements.txt").read_text().splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    names = {re.split(r"[<>=!~\[ ]", ln, maxsplit=1)[0].lower() for ln in lines}
    assert names == ALLOWED
    for ln in lines:
        assert ">=" in ln and "<" in ln, f"{ln!r} needs a lower bound and an upper bound on the next major"
        assert "==" not in ln
