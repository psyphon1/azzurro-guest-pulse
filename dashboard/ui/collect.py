"""The "Fetch latest reviews" button: starts scripts/collect_latest.py as a separate process.

The dashboard itself never writes to the database (it opens it read-only); the separate process does the writing,
and the page reloads its data when the database file changes. Collection needs a real, visible browser
(Playwright), so the button only appears where Playwright is installed, never on a hosted copy.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "data" / ".collect.lock"
STATUS = ROOT / "data" / ".collect.status.json"
LOG = ROOT / "data" / "collect.log"
COOLDOWN_S = 10 * 60          # at most one start every 10 minutes: protects Booking.com and our IP


def available(db_path: Path) -> tuple[bool, str]:
    """(can collect here?, reason if not)."""
    if os.environ.get("GUEST_PULSE_COLLECT", "1") == "0":
        return False, "Collection is switched off on this server."
    if importlib.util.find_spec("playwright") is None:
        return False, "Collection runs on the office computer (it needs a real browser), not on this hosted copy."
    if "sample" in db_path.name.lower() or "demo" in db_path.name.lower():
        return False, "You are viewing a snapshot; new reviews are added to the live database only."
    return True, ""


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def running() -> dict | None:
    """The lock contents while a collection runs, else None (a stale lock from a crashed run is removed)."""
    try:
        info = json.loads(LOCK.read_text())
    except (OSError, ValueError):
        return None
    if isinstance(info, dict) and _pid_alive(int(info.get("pid", 0) or 0)):
        return info
    LOCK.unlink(missing_ok=True)
    return None


def status() -> dict:
    try:
        data = json.loads(STATUS.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def seconds_until_allowed(now: float | None = None) -> int:
    now = time.time() if now is None else now
    try:
        started = datetime.fromisoformat(status().get("started_at", "")).timestamp()
    except (TypeError, ValueError):
        return 0
    return max(0, int(COOLDOWN_S - (now - started)))


def start(db_path: Path) -> tuple[bool, str]:
    """Start a collection unless one is running or the cooldown has not passed."""
    ok, why = available(db_path)
    if not ok:
        return False, why
    if running():
        return False, "A collection is already running."
    wait = seconds_until_allowed()
    if wait:
        return False, f"Please wait {wait // 60 + 1} more minute(s) before fetching again."
    LOG.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(json.dumps({"state": "starting", "started_at": datetime.now(timezone.utc).isoformat()}))
    with open(LOG, "w", encoding="utf-8") as log:
        subprocess.Popen([sys.executable, str(ROOT / "scripts" / "collect_latest.py"), "--db", str(db_path)],
                         cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    return True, "Started."


def log_tail(lines: int = 12) -> str:
    try:
        return "\n".join(LOG.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""
