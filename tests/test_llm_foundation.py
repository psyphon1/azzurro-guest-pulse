import sqlite3

import pytest

from app.config import DEFAULT_MODEL, estimate_cost, load_settings
from app.llm import FakeLLMClient, LLMError, get_client
from app.schema import ensure_schema


def test_no_key_means_layer_off():
    s = load_settings({})
    assert not s.enabled and s.model == DEFAULT_MODEL
    assert get_client(s) is None


def test_blank_key_is_off_and_model_comes_from_env():
    s = load_settings({"ANTHROPIC_API_KEY": "  ", "LLM_MODEL": "some-model"})
    assert not s.enabled and s.model == "some-model"


def test_cost_estimate_known_and_unknown_model():
    assert estimate_cost(DEFAULT_MODEL, 1_000_000, 0) == pytest.approx(0.10)
    assert estimate_cost("unknown", 10, 10) is None


def test_fake_client_replays_and_records():
    fake = FakeLLMClient([{"a": 1}, LLMError("boom")])
    assert fake.complete_json(system="s", user="u", schema={}).data == {"a": 1}
    with pytest.raises(LLMError):
        fake.complete_json(system="s", user="u2", schema={})
    with pytest.raises(LLMError):
        fake.complete_json(system="s", user="u3", schema={})
    assert [c[1] for c in fake.calls] == ["u", "u2", "u3"]


def test_schema_is_idempotent(tmp_path):
    con = sqlite3.connect(tmp_path / "x.db")
    ensure_schema(con)
    ensure_schema(con)
    names = {r[0] for r in con.execute("select name from sqlite_master where type='table'")}
    assert {"review_enrichment", "weekly_summary"} <= names
