"""周指标快照层单测: 周号算术 / 切窗聚合 / 幂等落盘 / 环比 / 消化工单建议。"""
import datetime as dt
import json

import pytest

from kb import metrics
from kb import trace


def _search(tid, caller, query, returned, ts):
    # layers.scanned=5: 避开 stats.synthetic_callers 的"全部≤2 判合成"剔噪
    return {"kind": "search", "trace_id": tid, "ts": ts, "source": "cli",
            "caller_repo": caller, "query": query, "returned": returned,
            "duration_ms": 10,
            "layers": [{"repo": "kb", "scanned": 5,
                        "rejected": {"filter": 0, "query": 4},
                        "matched": [{"id": i, "title": f"T{i}"} for i in returned],
                        "taken": len(returned), "truncated_at_limit": False}]}


def _get(tid, kid, caller, ts):
    return {"kind": "get", "trace_id": tid, "ts": ts, "id": kid,
            "caller_repo": caller, "ok": True, "chars": 800}


def _seed_week(root, monday: dt.date):
    """周内 2 检索(1 命中 1 零命中)+ 1 消费; 周外(day+20) 1 检索。"""
    at = lambda n: (monday + dt.timedelta(days=n)).isoformat() + "T10:00:00+08:00"
    for e in [_search("t1", "alpha", "推流 死锁", ["k1"], at(0)),
              _search("t2", "alpha", "授权 台账", [], at(1)),
              _get("t1", "k1", "alpha", at(0)),
              _search("t3", "alpha", "css slash", ["k2"], at(20))]:  # 周外
        trace.append_event(e, root=root)


def test_week_bounds_and_rejects_garbage():
    assert metrics.week_bounds("2026-W45") == ("2026-11-02", "2026-11-08")
    for bad in ("2026-45", "2026-W54", "2026-W4", "garbage", "", None):
        with pytest.raises(ValueError):
            metrics.week_bounds(bad)


def test_prev_of_is_iso_year_aware():
    assert metrics.prev_of("2026-W45") == "2026-W44"
    assert metrics.prev_of("2027-W01") == "2026-W53"   # 2026 是 53 周年
    assert metrics.prev_of("2026-W01") == "2025-W52"


def test_prev_week_default_is_previous_iso_week():
    assert metrics.prev_week(dt.date(2026, 11, 11)) == "2026-W45"  # 11-11 属 W46


def test_build_snapshot_window_and_schema(tmp_path):
    _seed_week(tmp_path, dt.date.fromisocalendar(2026, 45, 1))
    snap = metrics.build_snapshot(tmp_path, "2026-W45")
    assert set(snap) >= {"schema", "week", "since", "until", "generated_at",
                         "metrics", "latency", "zero_hit", "callers", "warns"}
    assert snap["schema"] == 1
    assert (snap["since"], snap["until"]) == ("2026-11-02", "2026-11-08")
    m = snap["metrics"]
    assert m["searches"] == 2                         # 周外 t3 不进分母
    assert m["hit_rate"] == 0.5                       # t1 命中 t2 零命中
    assert m["consume_rate"] == 1.0                   # 周内唯一返回条目被 get
    assert snap["latency"]["n"] == 2                  # 有 duration_ms 样本
    zh = snap["zero_hit"]
    assert [r["query"] for r in zh["board"]] == ["授权 台账"]
    assert zh["digested"] == 0 and zh["digest_rate"] == 0.0
    assert snap["callers"][0]["caller"] == "alpha"
    assert snap["warns"] == []


def test_write_snapshot_is_idempotent(tmp_path):
    _seed_week(tmp_path, dt.date.fromisocalendar(2026, 45, 1))
    snap = metrics.build_snapshot(tmp_path, "2026-W45")
    p = metrics.write_snapshot(tmp_path, snap)
    assert p.exists() and p.name == "2026-W45.json"
    # 往返断言: 只查文件存在会放过"写空文件/写 str(snap)"这类序列化损坏,
    # 必须真的读回并核对关键字段。
    back = json.loads(p.read_text(encoding="utf-8"))
    assert back["week"] == snap["week"] and back["schema"] == snap["schema"]
    assert isinstance(back, dict) and back["metrics"]["searches"] == snap["metrics"]["searches"]
    snaps, warns = metrics.load_snapshots(tmp_path)
    assert [s["week"] for s in snaps] == ["2026-W45"] and warns == []
    assert snaps[0]["zero_hit"]["digest_rate"] == snap["zero_hit"]["digest_rate"]
    with pytest.raises(FileExistsError):              # 幂等红线: 已存在拒覆盖
        metrics.write_snapshot(tmp_path, snap)
    assert metrics.write_snapshot(tmp_path, snap, force=True) == p


def test_build_snapshot_keeps_offline_caller(tmp_path):
    """只在窗口外活跃的项目必须留在 callers 里(掉线检测), 本周计数 0 且 stale。"""
    mon = dt.date.fromisocalendar(2026, 40, 1)   # 取已过去的周, 掉线才能判出来
    inside = (mon + dt.timedelta(days=1)).isoformat() + "T10:00:00+08:00"
    outside = (mon + dt.timedelta(days=20)).isoformat() + "T10:00:00+08:00"
    for e in (_search("s1", "alpha", "推流 死锁", ["k1"], inside),
              _search("s2", "beta", "授权 台账", [], outside)):   # 窗口外(且 >14d)
        trace.append_event(e, root=tmp_path)
    snap = metrics.build_snapshot(tmp_path, "2026-W40")
    by = {r["caller"]: r for r in snap["callers"]}
    assert set(by) == {"alpha", "beta"}
    assert by["beta"]["searches"] == 0 and by["beta"]["hit_rate"] is None
    assert by["beta"]["stale"] is True
    assert by["beta"]["last_ts"] == outside
    assert by["alpha"]["searches"] == 1   # 窗口内活动的项目统计列照旧


def test_load_snapshots_sorts_and_skips_broken(tmp_path):
    d = tmp_path / "traces" / "metrics"
    d.mkdir(parents=True)
    (d / "2026-W46.json").write_text('{"schema":1,"week":"2026-W46"}', encoding="utf-8")
    (d / "2026-W45.json").write_text('{"schema":1,"week":"2026-W45"}', encoding="utf-8")
    (d / "2026-W47.json").write_text("{坏的 json", encoding="utf-8")
    (d / "2026-W48.json").write_text('{"schema":1}', encoding="utf-8")   # 缺 week
    snaps, warns = metrics.load_snapshots(tmp_path)
    assert [s["week"] for s in snaps] == ["2026-W45", "2026-W46"]        # 排序+跳坏
    assert len(warns) == 2 and all("2026-W4" in w for w in warns)


def test_load_snapshots_skips_wrong_child_types(tmp_path):
    """合法 JSON 但子对象类型错(如 metrics 是 list)必须判坏跳过: 消费面
    会对其 .get(...) → AttributeError → /api/metrics 500。"""
    d = tmp_path / "traces" / "metrics"
    d.mkdir(parents=True)
    (d / "2026-W45.json").write_text(
        '{"week":"2026-W45","metrics":[1,2]}', encoding="utf-8")
    (d / "2026-W46.json").write_text(
        '{"week":"2026-W46","metrics":{"searches":1},"callers":"alpha"}',
        encoding="utf-8")
    (d / "2026-W47.json").write_text(
        '{"week":"2026-W47","metrics":{"searches":1},"callers":[]}',
        encoding="utf-8")
    snaps, warns = metrics.load_snapshots(tmp_path)     # 不抛异常
    assert [s["week"] for s in snaps] == ["2026-W47"]   # 坏文件不进结果
    assert len(warns) == 2
    assert any("2026-W45.json" in w for w in warns)     # warns 可定位到文件
    assert any("2026-W46.json" in w for w in warns)


def test_load_snapshots_empty_root(tmp_path):
    assert metrics.load_snapshots(tmp_path) == ([], [])


def test_delta_two_branches():
    cur = {"metrics": {"hit_rate": 0.8, "consume_rate": 0.5, "searches": 10},
           "zero_hit": {"digest_rate": 0.25}, "latency": {"p50_ms": 120}}
    prev = {"metrics": {"hit_rate": 0.6, "consume_rate": 0.5, "searches": 4},
            "zero_hit": {"digest_rate": 0.5}, "latency": {"p50_ms": 100}}
    d = metrics.delta(cur, prev)
    assert d["hit_rate"] == {"cur": 0.8, "prev": 0.6, "diff": 0.2}
    assert d["consume_rate"]["diff"] == 0.0
    assert d["digest_rate"]["diff"] == -0.25
    d2 = metrics.delta(cur, None)                     # 上周快照缺失 → 只报绝对值
    assert d2["hit_rate"] == {"cur": 0.8, "prev": None, "diff": None}


def test_digest_plan_prefers_existing_then_novels(tmp_path):
    (tmp_path / "kb").mkdir()
    (tmp_path / "kb" / "index.jsonl").write_text(json.dumps({
        "id": "kb-20261012-7f3a", "title": "Vite HMR 失效排查", "type": "pitfall",
        "domain": "frontend", "scope": "stack", "status": "accepted",
        "confidence": "verified", "tags": ["vite", "hmr"], "keywords": [],
        "summary": "HMR 不刷新的根因", "path": "kb/pitfall/frontend/vite-hmr.md"},
        ensure_ascii=False), encoding="utf-8")
    snap = {"zero_hit": {"board": [
        {"query": "vite", "count": 3, "caller": "alpha",
         "last_ts": "2026-11-03T10:00:00+08:00", "digested": False},
        {"query": "推流 死锁 rtmp", "count": 2, "caller": "alpha",
         "last_ts": "2026-11-04T10:00:00+08:00", "digested": False},
        {"query": "已消化词", "count": 1, "digested": True}]}}
    plan = metrics.digest_plan(tmp_path, snap)
    # 已消化不进清单; "vite" 应命中索引(title/tags), 无匹配的退"立新条"
    assert [p["query"] for p in plan] == ["vite", "推流 死锁 rtmp"]
    by_q = {p["query"]: p for p in plan}
    assert by_q["vite"]["targets"] and "tags" in by_q["vite"]["action"]
    assert by_q["推流 死锁 rtmp"]["targets"] == []
    assert "立新条" in by_q["推流 死锁 rtmp"]["action"]
    # 若评分面意外零命中致断言失败: 调整的是索引 fixture 的 tags/title 用词, 不改实现


def test_digest_plan_without_index(tmp_path):
    """空仓(无 kb/index.jsonl)不炸: 全部退化为"立新条"。"""
    plan = metrics.digest_plan(tmp_path, {"zero_hit": {"board": [
        {"query": "x y", "count": 1, "digested": False}]}})
    assert plan[0]["action"].startswith("立新条")


def test_report_markdown_shows_delta_and_ticket():
    cur = {"schema": 1, "week": "2026-W45", "since": "2026-11-02",
           "until": "2026-11-08",
           "metrics": {"searches": 10, "hit_rate": 0.8, "consume_rate": 0.5,
                       "cold_start": False},
           "latency": {"n": 8, "p50_ms": 120, "p95_ms": 400, "avg_ms": 150,
                       "max_ms": 700},
           "zero_hit": {"board": [{"query": "vite hmr", "count": 3,
                                   "caller": "alpha",
                                   "last_ts": "2026-11-03T10:00:00+08:00",
                                   "digested": False}],
                        "digested": 0, "digest_rate": 0.0},
           "callers": [{"caller": "alpha", "searches": 10, "hit_rate": 0.8,
                        "last_ts": "2026-11-08T10:00:00+08:00", "stale": False}],
           "warns": []}
    prev = {"metrics": {"searches": 4, "hit_rate": 0.6, "consume_rate": 0.5},
            "zero_hit": {"digest_rate": 0.5}, "latency": {"p50_ms": 100}}
    md = metrics.report_markdown(cur, prev, [
        {"query": "vite hmr", "count": 3,
         "action": "补 tags(中英各一组) / 改 summary",
         "targets": [{"id": "kb-20261012-7f3a", "title": "Vite HMR 失效排查"}]}])
    assert "2026-W45" in md and "2026-11-02" in md
    assert "+20.0pp" in md                            # 命中率环比
    assert "kb-20261012-7f3a" in md                   # 工单指向目标条目 id
    md2 = metrics.report_markdown(cur, None, [])
    assert "上周快照缺失" in md2                       # 环比缺失分支如实标注
