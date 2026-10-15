import itertools

import pytest

from kb import spider_export


def _trace():
    return {"kind": "search", "trace_id": "t-1", "ts": "2026-10-15T14:32:05+08:00",
            "source": "mcp", "caller_repo": "flysee_video_web", "query": "vite hmr",
            "filters": {"type": "pitfall", "domain": "frontend"}, "limit": 10,
            "duration_ms": 8,
            "layers": [
                {"repo": "docs", "scanned": 208, "rejected": {"filter": 150, "query": 40},
                 "matched": [{"id": "kb-a", "title": "vite hmr DOM 失效", "scope": "project",
                               "confidence": "verified", "hit_fields": ["title", "tags"],
                               "hit_spans": [[0, 4]], "rank": 1}],
                 "taken": 1, "truncated_at_limit": False},
                {"repo": "kb", "scanned": 195, "rejected": {"filter": 0, "query": 194},
                 "matched": [{"id": "kb-b", "title": "keep-alive SSE", "scope": "stack",
                               "confidence": "probable", "hit_fields": ["summary"],
                               "hit_spans": [[10, 14]], "rank": 1}],
                 "taken": 1, "truncated_at_limit": False}],
            "returned": ["kb-a", "kb-b"]}


def _gets():
    return [{"kind": "get", "trace_id": "t-1", "ts": "2026-10-15T14:33:00+08:00",
             "source": "mcp", "caller_repo": "flysee_video_web", "id": "kb-a",
             "layer": "docs", "ok": True},
            {"kind": "get", "trace_id": "t-9", "ts": "2026-10-15T15:00:00+08:00",
             "source": "mcp", "caller_repo": "flysee_video_web", "id": "kb-z",
             "layer": "docs", "ok": True}]


def test_record_shape():
    rec = spider_export.to_record(_trace(), _gets())
    assert rec["format"] == "prompt-spider-session/v1"
    assert rec["config"]["title"].startswith("KB 命中")
    assert rec["config"]["unit"] == "task"
    labels = {r["label"] for r in rec["config"]["routes"].values()}
    assert labels == {"项目层命中", "通用层命中", "已读消费"}


def test_events_and_routes():
    rec = spider_export.to_record(_trace(), _gets())
    by_id = {e["id"]: e for e in rec["events"]}
    assert set(by_id) == {"kb-a", "kb-b"}
    assert by_id["kb-a"]["route"] == "you"          # 被 kb_get 消费 → 已读分支
    assert by_id["kb-b"]["route"] == "model"        # 通用层命中
    assert "hit: title+tags" in by_id["kb-a"]["detail"]
    assert by_id["kb-b"]["detail"].startswith("hit: summary")


def test_log_monotonic_and_revision_ordered():
    rec = spider_export.to_record(_trace(), _gets())
    log = rec["log"]
    assert [e["revision"] for e in log] == list(range(1, len(log) + 1))
    assert all(b["at"] >= a["at"] for a, b in itertools.pairwise(log))
    assert log[0]["at"] >= 0


def test_zero_hit_trace_valid():
    tr = _trace()
    tr["layers"] = [{**tr["layers"][0], "matched": [], "taken": 0}]
    tr["returned"] = []
    rec = spider_export.to_record(tr, [])
    assert rec["events"] == []
    assert "0 命中" in rec["config"]["subtitle"]


def test_unrelated_get_ignored():
    rec = spider_export.to_record(_trace(), _gets())   # kb-z/t-9 不在本 trace
    assert {e["id"] for e in rec["events"]} == {"kb-a", "kb-b"}
    assert rec["events"][0]["status"] == "completed"


def test_deterministic():
    a = spider_export.to_record(_trace(), _gets())
    b = spider_export.to_record(_trace(), _gets())
    assert a == b


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "agent-kb"
    root.mkdir()
    monkeypatch.setattr("kb.trace.kb_root", lambda: root)
    return root


def test_cli_export(env, tmp_path, capsys):
    from kb import trace as tr
    from kb.cli import main
    tr.append_event(_trace(), root=env)
    for g in _gets():
        tr.append_event(g, root=env)
    out = tmp_path / "rec.json"
    assert main(["trace", "export", "t-1", "-o", str(out)]) == 0
    import json
    rec = json.loads(out.read_text(encoding="utf-8"))
    assert rec["format"] == "prompt-spider-session/v1"
