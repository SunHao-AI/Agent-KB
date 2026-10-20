"""B-1 FR-5.2: 按源堆叠聚合 + 矩阵行扩展 + 外接源健康(纯函数)。"""
from kb import stats


def _search(tid, caller, returned, layers, ext=None, ts="2026-10-20T10:00:00+08:00"):
    return {"kind": "search", "trace_id": tid, "caller_repo": caller, "ts": ts,
            "query": "q", "returned": returned, "layers": layers,
            "ext": ext or []}


def _layer(repo, ids):
    return {"repo": repo, "scanned": 10, "rejected": {"filter": 0, "query": 5},
            "matched": [{"id": i, "title": f"T{i}", "hit_fields": ["title"]} for i in ids],
            "taken": len(ids), "truncated_at_limit": False}


def test_by_source_three_kinds():
    S = [_search("t1", "web", ["p1", "s1", "source://tdbm/wiki-a"],
                 [_layer("docs", ["p1"]), _layer("kb", ["s1"])],
                 ext=[{"source": "tdbm", "ok": True, "hits": ["source://tdbm/wiki-a"]}])]
    bs = stats.by_source(S)["web"]
    assert bs == {"project": 1, "stack": 1, "ext:tdbm": 1}


def test_by_source_unmatched_falls_to_stack():
    # schema=1 老事件 layers 明细可能缺 matched: 非 ext 命中兜底记 stack(不虚增 project)
    S = [_search("t1", "web", ["x9"], [])]
    assert stats.by_source(S)["web"] == {"stack": 1}


def test_callers_rows_carry_source_and_ext_health():
    S = [_search("t1", "web", ["p1", "source://tdbm/a"], [_layer("docs", ["p1"])],
                 ext=[{"source": "tdbm", "ok": True, "hits": ["source://tdbm/a"]}],
                 ts="2026-10-19T10:00:00+08:00"),
         _search("t2", "web", [], [],
                 ext=[{"source": "tdbm", "ok": False, "error": "timeout"}],
                 ts="2026-10-20T10:00:00+08:00")]
    rows = {r["caller"]: r for r in stats.callers(S)}
    web = rows["web"]
    assert web["by_source"] == {"project": 1, "ext:tdbm": 1}
    # 健康态取最近一次: tdbm 最新是失败(timeout)
    assert web["ext"] == [{"source": "tdbm", "ok": False, "error": "timeout"}]


def test_source_of_parses_connector():
    assert stats.source_of("source://tdbm/wiki/x.md", []) == "ext:tdbm"
    assert stats.source_of("kb-2026-0001", []) is None
