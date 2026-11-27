"""Browser test harness: start the real Streamlit app, drive it with Playwright, and WATCH everything that comes out.

Watched on every page: browser console errors, uncaught page errors, failed or 4xx/5xx network requests, any request
to a host other than localhost (a privacy leak or an injected beacon), and JavaScript dialogs (a sign of script execution).
Watched on the server: the app's own log, which must contain no traceback or error line.
"""
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "dashboard" / "app.py"

# Lines in the server log that are noise, not problems.
LOG_ALLOW = [
    re.compile(r"You can now view your Streamlit app"),
    re.compile(r"Local URL|Network URL|External URL"),
    re.compile(r"Stopping\.\.\."),
]
LOG_BAD = re.compile(r"Traceback|Exception|Error|CRITICAL|WARNING|Warning|deprecat", re.IGNORECASE)

# Requests that are allowed to fail or be non-200 without meaning the app is broken.
RESPONSE_ALLOW = [
    re.compile(r"/favicon"),
    re.compile(r"/_stcore/(metrics|host-config)"),
]
LOCAL_HOSTS = {"127.0.0.1", "localhost", ""}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class AppServer:
    """A real `streamlit run dashboard/app.py` process against one database, with its log captured."""

    def __init__(self, db_path: str, extra_env: dict | None = None):
        self.db_path = str(db_path)
        self.port = free_port()
        self.url = f"http://127.0.0.1:{self.port}"
        self._log = tempfile.NamedTemporaryFile("w+", suffix=".log", delete=False)
        env = {**os.environ, "REVIEWS_DB": self.db_path, "PYTHONUNBUFFERED": "1", **(extra_env or {})}
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", str(APP), "--server.headless", "true",
             "--server.port", str(self.port), "--server.address", "127.0.0.1",
             "--browser.gatherUsageStats", "false"],
            cwd=str(ROOT), env=env, stdout=self._log, stderr=subprocess.STDOUT)
        self._wait_healthy()

    def _wait_healthy(self, timeout: float = 40.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"Streamlit exited early:\n{self.log()}")
            try:
                with urllib.request.urlopen(self.url + "/_stcore/health", timeout=2) as r:
                    if r.read().strip() == b"ok":
                        return
            except OSError:
                pass
            time.sleep(0.3)
        raise RuntimeError(f"Streamlit did not become healthy in {timeout}s:\n{self.log()}")

    def log(self) -> str:
        self._log.flush()
        return Path(self._log.name).read_text(errors="replace")

    def bad_log_lines(self) -> list[str]:
        return [ln for ln in self.log().splitlines()
                if LOG_BAD.search(ln) and not any(p.search(ln) for p in LOG_ALLOW)]

    def stop(self) -> None:
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        self._log.close()
        try:
            os.unlink(self._log.name)
        except OSError:
            pass


class Monitor:
    """Collects everything suspicious a page does. Call assert_clean() at the end of a test."""

    def __init__(self, page, allow_external: bool = False):
        self.console_errors: list[str] = []
        self.console_warnings: list[str] = []
        self.page_errors: list[str] = []
        self.failed_requests: list[str] = []
        self.bad_responses: list[str] = []
        self.external_requests: list[str] = []
        self.dialogs: list[str] = []
        self.requests_seen = 0
        self.allow_external = allow_external
        page.on("console", self._console)
        page.on("pageerror", lambda e: self.page_errors.append(str(e)[:300]))
        page.on("requestfailed", self._failed)
        page.on("request", self._request)
        page.on("response", self._response)
        page.on("dialog", self._dialog)

    def _console(self, msg):
        text = f"{msg.text[:300]}"
        if msg.type == "error":
            self.console_errors.append(text)
        elif msg.type == "warning":
            self.console_warnings.append(text)

    def _failed(self, req):
        if "net::ERR_ABORTED" in (req.failure or ""):
            return                                     # a navigation or cancelled fetch, not a fault
        self.failed_requests.append(f"{req.method} {req.url[:120]} {req.failure}")

    def _request(self, req):
        self.requests_seen += 1
        parts = urlsplit(req.url)
        if parts.scheme in ("http", "https") and parts.hostname not in LOCAL_HOSTS:
            self.external_requests.append(req.url[:160])

    def _response(self, resp):
        if resp.status >= 400 and not any(p.search(resp.url) for p in RESPONSE_ALLOW):
            self.bad_responses.append(f"{resp.status} {resp.url[:140]}")

    def _dialog(self, dialog):
        self.dialogs.append(f"{dialog.type}: {dialog.message[:100]}")
        dialog.dismiss()

    def problems(self) -> dict[str, list[str]]:
        out = {"console_errors": self.console_errors, "page_errors": self.page_errors,
               "failed_requests": self.failed_requests, "bad_responses": self.bad_responses,
               "dialogs": self.dialogs}
        if not self.allow_external:
            out["external_requests"] = self.external_requests
        return {k: v for k, v in out.items() if v}

    def assert_clean(self) -> None:
        problems = self.problems()
        assert not problems, f"browser monitor found problems: {problems}"


def wait_for_app(page, timeout_ms: int = 30000) -> None:
    """Wait until Streamlit has finished running the script (the 'Running...' indicator is gone and has stayed gone)."""
    page.wait_for_selector('[data-testid="stApp"]', timeout=timeout_ms)
    settle(page, timeout_ms)


def settle(page, timeout_ms: int = 20000) -> None:
    """After any interaction: wait for the rerun to start and finish."""
    page.wait_for_timeout(350)
    deadline = time.time() + timeout_ms / 1000
    quiet_since = None
    while time.time() < deadline:
        busy = page.locator('[data-testid="stStatusWidget"]').count() > 0
        if busy:
            quiet_since = None
        else:
            quiet_since = quiet_since or time.time()
            if time.time() - quiet_since > 0.6:
                return
        page.wait_for_timeout(120)
    raise AssertionError("the app never finished running (stuck on 'Running...')")


def main_text(page) -> str:
    return page.locator('[data-testid="stMain"]').inner_text()


# ------------------------------------------------------------------------------------------------ interaction helpers
HOTELS = ["Olympic Hotel Paddington", "Potts Point", "Central Sydney", "Darling Harbour"]


def sidebar(page):
    return page.locator('[data-testid="stSidebar"]')


def choose(page, label: str, option: str) -> None:
    """Pick an option in a Streamlit selectbox by its visible label."""
    page.get_by_role("combobox", name=label).click()
    page.get_by_role("option", name=option, exact=True).click()
    settle(page)


def only_hotels(page, keep: list[str]) -> None:
    """Leave exactly the named hotels selected in the sidebar multiselect (removes the others via their x buttons)."""
    for name in HOTELS:
        if name not in keep and sidebar(page).get_by_role("button", name=f"Remove {name}").count():
            sidebar(page).get_by_role("button", name=f"Remove {name}").click()
            settle(page)


def clear_hotels(page) -> None:
    sidebar(page).get_by_role("button", name="Clear all").click()
    settle(page)


def tick(page, label: str, on: bool = True) -> None:
    box = page.locator('[data-testid="stCheckbox"]', has_text=label)
    if box.locator('input[type="checkbox"]').is_checked() != on:
        box.click()
        settle(page)


def download_csv(page) -> tuple[str, str]:
    """Click the feed's CSV button and return (suggested file name, decoded content)."""
    with page.expect_download() as info:
        page.get_by_role("button", name="Download these reviews as CSV").click()
    d = info.value
    with open(d.path(), "rb") as fh:
        return d.suggested_filename, fh.read().decode("utf-8-sig")


def search(page, text: str) -> None:
    box = page.get_by_label("Search the text")
    box.fill(text)
    box.press("Enter")
    settle(page)


def cards(page):
    return page.locator(".az-review")


def card_scores(page) -> list[float]:
    import re
    return [float(re.search(r"(\d+(?:\.\d+)?)/10", t).group(1)) for t in page.locator(".az-review .az-score").all_inner_texts()]


def feed_total(page) -> int:
    import re
    m = re.search(r"([\d,]+) reviews? match", main_text(page))
    return int(m.group(1).replace(",", "")) if m else 0


def exception_boxes(page) -> int:
    return page.locator('[data-testid="stException"]').count()


def no_traceback(page) -> None:
    text = page.locator("body").inner_text()
    for bad in ("Traceback", "File \"/", "sqlite3.", "OperationalError", "KeyError", "AttributeError"):
        assert bad not in text, f"internal error text leaked to the page: {bad}"
    assert exception_boxes(page) == 0


CONTRAST_JS = """
(selector) => {
  function lum(c){ const a=c.map(v=>{v/=255; return v<=0.03928? v/12.92 : Math.pow((v+0.055)/1.055,2.4)}); return 0.2126*a[0]+0.7152*a[1]+0.0722*a[2]; }
  function parse(s){ const m=s.match(/rgba?\\(([^)]+)\\)/); if(!m) return null; const p=m[1].split(',').map(x=>parseFloat(x)); return {r:p[0],g:p[1],b:p[2],a:p.length>3?p[3]:1}; }
  function bg(el){ let e=el; let layers=[]; while(e){ const c=parse(getComputedStyle(e).backgroundColor); if(c && c.a>0){ layers.push(c); if(c.a>=1) break; } e=e.parentElement; }
    let base={r:255,g:255,b:255}; for(let i=layers.length-1;i>=0;i--){ const c=layers[i]; base={r:c.r*c.a+base.r*(1-c.a), g:c.g*c.a+base.g*(1-c.a), b:c.b*c.a+base.b*(1-c.a)}; } return base; }
  const out=[]; document.querySelectorAll(selector).forEach(el=>{
    if(!el.offsetParent) return; const fg=parse(getComputedStyle(el).color); if(!fg) return; const b=bg(el);
    const l1=lum([fg.r,fg.g,fg.b]), l2=lum([b.r,b.g,b.b]); const ratio=(Math.max(l1,l2)+0.05)/(Math.min(l1,l2)+0.05);
    out.push({text:(el.innerText||'').trim().slice(0,40), ratio:Math.round(ratio*100)/100, size:parseFloat(getComputedStyle(el).fontSize)});
  }); return out; }
"""
