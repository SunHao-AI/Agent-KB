import json

import pytest

from kb import trace
from kb.cli import main


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "agent-kb"
    root.mkdir()
    monkeypatch.setattr(trace, "kb_root", lambda: root)
    return root


def _seed(root):
    for i, caller in enumerate(["web", "algo"]):
        trace.append_event({"kind": "search", "trace_id": f"t-1{i}", "ts": f"2026-10-1{i + 4}T10:00:00+08:00",
                            "source": "cli", "caller_repo": caller, "query": f"q{i}",
                            "filters": {}, "limit": 10, "duration_ms": 2,
                            "layers": [], "returned": ["kb-1"] if i == 0 else []}, root=root)


def test_list_empty_guidance(env, capsys):
    assert main(["trace", "list"]) == 0
    out = capsys.readouterr().out
    assert "KB_TRACE" in out           # 引导语指向开关


def test_list_table_and_filters(env, capsys):
    _seed(env)
    assert main(["trace", "list"]) == 0
    out = capsys.readouterr().out
    assert "t-11" in out and "t-10" in out and "0命中" in out
    assert main(["trace", "list", "--caller", "web"]) == 0
    out = capsys.readouterr().out
    assert "t-10" in out and "t-11" not in out
    assert main(["trace", "list", "--since", "2026-10-15"]) == 0
    out = capsys.readouterr().out
    assert "t-11" in out and "t-10" not in out   # seed ts: t-10=10-14, t-11=10-15


def test_show_found_and_missing(env, capsys):
    _seed(env)
    assert main(["trace", "show", "t-10"]) == 0
    assert json.loads(capsys.readouterr().out)["trace_id"] == "t-10"
    assert main(["trace", "show", "nope"]) == 1
