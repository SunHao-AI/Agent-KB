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
    assert labels == {"项目层命中", "通用层命中", "外接源命中", "已读消费"}


def test_spider_id_sanitizes_and_roundtrips():
    import re
    ok = re.compile(r"^[\w.:-]+$", re.UNICODE)
    # source:// 原生 id 含 '/', 对端正则会拒(真机校准) → '/'归一为'-', ':'与'.'保留
    assert spider_export.spider_id("source://tdbm/wiki/redis.md") == "source:--tdbm-wiki-redis.md"
    assert ok.match(spider_export.spider_id("source://tdbm/wiki/redis.md"))
    # 普通 kb id 原样保留(search/get 两侧同函数, you 匹配不断)
    assert spider_export.spider_id("kb-20261012-7f3a") == "kb-20261012-7f3a"


def test_ext_hits_are_ext_route_and_sanitized():
    tr = _trace()
    tr["returned"] = ["kb-a", "source://tdbm/wiki/redis.md"]
    tr["ext"] = [{"source": "tdbm", "ok": True, "hits": ["source://tdbm/wiki/redis.md"]}]
    rec = spider_export.to_record(tr, _gets())
    by_id = {e["id"]: e for e in rec["events"]}
    sid = "source:--tdbm-wiki-redis.md"
    assert by_id[sid]["route"] == "ext"
    assert by_id[sid]["detail"] == "source://tdbm"
    # consumed 回原生 id(仓内语义), 不是归一后的
    assert rec["consumed"] == ["kb-a"]


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


def test_subtitle_truncation_note():
    tr = _trace()
    tr["layers"][1]["truncated_at_limit"] = True
    rec = spider_export.to_record(tr, _gets())
    assert " | 截断于kb层" in rec["config"]["subtitle"]
    # 无截断层时不追加注记
    assert "截断于" not in spider_export.to_record(_trace(), _gets())["config"]["subtitle"]


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


def test_record_matches_validator_contract():
    """对端 validateRecord 硬要求: version/duration/status + log type 字段。"""
    rec = spider_export.to_record(_trace(), _gets())
    assert rec["version"] == 1
    assert rec["status"] == "completed"
    assert isinstance(rec["duration"], (int, float))
    assert rec["duration"] >= max(e["at"] for e in rec["log"])
    assert {e["type"] for e in rec["log"]} <= {"configure", "events", "complete"}
    assert rec["log"][0]["type"] == "configure"
    assert rec["log"][-1]["type"] == "complete"
    # 每条 events 批 1..100
    for e in rec["log"]:
        if e["type"] == "events":
            assert 1 <= len(e["events"]) <= 100


def test_subtitle_within_160():
    tr = _trace()
    tr["layers"][0]["repo"] = "R" * 200
    rec = spider_export.to_record(tr, _gets())
    assert len(rec["config"]["subtitle"]) <= 160


def test_all_consumed_no_empty_running_batch():
    tr = _trace()
    tr["returned"] = ["kb-a", "kb-b"]
    gets = [{"kind": "get", "trace_id": "t-1", "id": "kb-a", "caller_repo": "w",
             "layer": "docs", "ok": True, "source": "mcp", "ts": "x"},
            {"kind": "get", "trace_id": "t-1", "id": "kb-b", "caller_repo": "w",
             "layer": "kb", "ok": True, "source": "mcp", "ts": "x"}]
    rec = spider_export.to_record(tr, gets)
    # 无 running 事件时不得产生空 events 批
    for e in rec["log"]:
        if e["type"] == "events":
            assert len(e["events"]) >= 1


def test_events_chunked_over_100():
    tr = _trace()
    ids = [f"kb-{i}" for i in range(150)]
    tr["returned"] = ids
    tr["layers"] = [{"repo": "docs", "scanned": 400,
                     "rejected": {"filter": 0, "query": 250},
                     "matched": [{"id": i, "title": f"t{i}", "scope": "project",
                                   "confidence": "verified", "hit_fields": ["title"],
                                   "hit_spans": [[0, 1]], "rank": n}
                                  for n, i in enumerate(ids)],
                     "taken": 150, "truncated_at_limit": False}]
    rec = spider_export.to_record(tr, [])
    assert len(rec["events"]) == 150
    ev_batches = [e for e in rec["log"] if e["type"] == "events"]
    assert all(len(b["events"]) <= 100 for b in ev_batches)
    # completed 批合计覆盖 150 个唯一 id
    done = [b for b in ev_batches if all(x["status"] == "completed" for x in b["events"])]
    seen = {x["id"] for b in done for x in b["events"]}
    assert seen == set(ids)


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


def test_cli_export_latest(env, tmp_path, capsys):
    """--latest 免手输 id; --caller 限定取该 agent 的最近一次。"""
    from kb import trace as tr
    from kb.cli import main
    a = _trace()
    a["trace_id"], a["caller_repo"], a["ts"] = "t-old", "web", "2026-10-14T10:00:00+08:00"
    b = _trace()
    b["trace_id"], b["caller_repo"], b["ts"] = "t-new", "algo", "2026-10-15T10:00:00+08:00"
    for ev in (a, b):
        tr.append_event(ev, root=env)
    out = tmp_path / "r.json"
    assert main(["trace", "export", "--latest", "-o", str(out)]) == 0
    import json
    assert json.loads(out.read_text(encoding="utf-8"))["id"] == "t-new"
    assert main(["trace", "export", "--latest", "--caller", "web",
                 "-o", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["id"] == "t-old"


def test_cli_export_latest_empty_is_error(env, tmp_path, capsys):
    from kb.cli import main
    assert main(["trace", "export", "--latest",
                 "-o", str(tmp_path / "x.json")]) == 1
    assert "no trace" in capsys.readouterr().err


def test_cli_export_requires_id_or_latest(env, capsys):
    from kb.cli import main
    assert main(["trace", "export"]) == 2
    assert main(["trace", "export", "t-1", "--latest"]) == 2


def test_cli_export_id_and_caller_is_error(env, capsys):
    from kb.cli import main
    assert main(["trace", "export", "t-1", "--caller", "web"]) == 2
