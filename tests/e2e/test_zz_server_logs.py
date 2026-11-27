"""The last test of the run: every server started for these tests must have a clean log (no traceback, no error,
no warning, no deprecation notice) after everything the browser did to it."""
from tests.e2e.conftest import SERVERS


def test_no_server_logged_a_problem():
    assert SERVERS, "no server was started: the browser tests did not run"
    problems = {s.db_path.split("/")[-1]: s.bad_log_lines() for s in SERVERS}
    problems = {k: v for k, v in problems.items() if v}
    assert not problems, f"server logs contain problems: {problems}"
