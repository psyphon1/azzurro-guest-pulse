import tempfile
from pathlib import Path

import pytest

from tests.e2e import dbs
from tests.e2e.harness import AppServer, Monitor, wait_for_app


E2E_DIR = Path(__file__).resolve().parent


def pytest_collection_modifyitems(items):
    for item in items:
        # this hook sees EVERY collected test in the session: only mark the ones that live in tests/e2e
        if E2E_DIR in Path(str(item.fspath)).resolve().parents:
            item.add_marker(pytest.mark.e2e)


@pytest.fixture(scope="session")
def e2e_folder():
    with tempfile.TemporaryDirectory(prefix="azzurro-e2e-") as d:
        yield Path(d)


@pytest.fixture(scope="session")
def playwright_browser():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)       # headless is fine: this is our own localhost app
        except Exception as exc:                              # pragma: no cover - browser not installed
            pytest.skip(f"Chromium is not installed (run: python -m playwright install chromium): {exc}")
        yield browser
        browser.close()


SERVERS: list = []          # every server started in this run, so the final test can check all their logs


def _server(request, path):
    server = AppServer(path)
    SERVERS.append(server)
    request.addfinalizer(server.stop)
    return server


@pytest.fixture(scope="session")
def main_server(request, e2e_folder):
    return _server(request, dbs.main_db(e2e_folder))


@pytest.fixture(scope="session")
def evil_server(request, e2e_folder):
    return _server(request, dbs.evil_db(e2e_folder))


@pytest.fixture(scope="session")
def empty_server(request, e2e_folder):
    return _server(request, dbs.empty_db(e2e_folder))


@pytest.fixture(scope="session")
def big_server(request, e2e_folder):
    return _server(request, dbs.big_db(e2e_folder))


@pytest.fixture(scope="session")
def corrupt_server(request, e2e_folder):
    return _server(request, dbs.corrupt_db(e2e_folder))


@pytest.fixture(scope="session")
def missing_server(request, e2e_folder):
    return _server(request, e2e_folder / "does_not_exist.db")


@pytest.fixture(scope="session")
def sample_server(request, e2e_folder, main_server):
    return _server(request, dbs.renamed_copy(Path(main_server.db_path), "reviews_sample.db"))


@pytest.fixture(scope="session")
def demo_server(request, e2e_folder, main_server):
    return _server(request, dbs.renamed_copy(Path(main_server.db_path), "azzurro_demo.db"))


@pytest.fixture
def open_app(playwright_browser):
    """open_app(server, viewport=None, allow_external=False) -> (page, monitor). Fresh browser context per test."""
    contexts = []

    def _open(server, viewport=None, allow_external=False, accept_downloads=True):
        ctx = playwright_browser.new_context(viewport=viewport or {"width": 1280, "height": 900},
                                             accept_downloads=accept_downloads)
        contexts.append(ctx)
        page = ctx.new_page()
        monitor = Monitor(page, allow_external=allow_external)
        page.goto(server.url, timeout=45000)
        wait_for_app(page)
        return page, monitor

    yield _open
    for ctx in contexts:
        ctx.close()
