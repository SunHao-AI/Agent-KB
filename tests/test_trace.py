import datetime as dt
import json

import pytest

from kb import trace


@pytest.fixture
def kbroot(tmp_path, monkeypatch):
    """Agent-KB 仓根指向 tmp, 隔离真实 traces/。"""
    root = tmp_path / "agent-kb"
    root.mkdir()
    monkeypatch.setattr(trace, "kb_root", lambda: root)
    monkeypatch.delenv("KB_TRACE", raising=False)
    return root


def test_kb_root_points_to_repo_root():
    # src/kb/trace.py 的 parents[1] 必须是含 pyproject.toml 的仓根
    assert (trace.kb_root() / "pyproject.toml").exists()


def test_default_off(kbroot):
    assert trace.trace_enabled() is False


def test_cli_off_overrides_env_on(kbroot, monkeypatch):
    monkeypatch.setenv("KB_TRACE", "1")
    assert trace.trace_enabled(cli_flag=False) is False


def test_cli_on_overrides_env_off(kbroot, monkeypatch):
    monkeypatch.setenv("KB_TRACE", "0")
    assert trace.trace_enabled(cli_flag=True) is True


def test_env_on(kbroot, monkeypatch):
    monkeypatch.setenv("KB_TRACE", "1")
    assert trace.trace_enabled() is True


def test_env_zero_beats_marker(kbroot, monkeypatch):
    monkeypatch.setenv("KB_TRACE", "0")
    (kbroot / ".kb-trace").write_text("", encoding="utf-8")
    assert trace.trace_enabled() is False


def test_marker_file(kbroot):
    (kbroot / ".kb-trace").write_text("", encoding="utf-8")
    assert trace.trace_enabled() is True


def _ev(i, kind="search", caller="web", returned=("kb-a",),
        ts="2026-10-15T14:32:05+08:00"):
    if kind == "get":
        return {"kind": "get", "trace_id": f"t-{i}", "ts": ts, "id": "kb-a",
                "layer": "docs", "ok": True, "source": "mcp", "caller_repo": caller}
    return {"kind": "search", "trace_id": f"t-{i}", "ts": ts, "source": "cli",
            "caller_repo": caller, "query": f"q{i}", "filters": {}, "limit": 10,
            "duration_ms": 3, "layers": [], "returned": list(returned)}


def _write(kbroot, name, lines):
    d = kbroot / "traces"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text("".join(json.dumps(x, ensure_ascii=False) + "\n"
                                  if not isinstance(x, str) else x + "\n"
                                  for x in lines), encoding="utf-8")
    return d


def test_new_file_writes_meta_once(kbroot):
    trace.append_event(_ev(1), root=kbroot)
    trace.append_event(_ev(2), root=kbroot)
    files = list((kbroot / "traces").glob("*.jsonl"))
    assert len(files) == 1                      # 同日单文件
    lines = files[0].read_text(encoding="utf-8").splitlines()
    metas = [ln for ln in lines if json.loads(ln).get("kind") == "meta"]
    assert len(metas) == 1
    assert json.loads(metas[0]) == {"kind": "meta", "schema": trace.SCHEMA}
    assert len(lines) == 3


def test_read_splits_search_and_get(kbroot):
    trace.append_event(_ev(1), root=kbroot)
    trace.append_event(_ev(1, kind="get"), root=kbroot)
    searches, gets, warns = trace.read_traces(root=kbroot)
    assert [s["trace_id"] for s in searches] == ["t-1"]
    assert [g["trace_id"] for g in gets] == ["t-1"]
    assert warns == []


def test_read_missing_dir(kbroot):
    searches, gets, warns = trace.read_traces(root=kbroot)
    assert (searches, gets, warns) == ([], [], [])


def test_read_skips_file_without_meta(kbroot):
    _write(kbroot, "2026-01-01.jsonl", [_ev(9)])
    searches, _, warns = trace.read_traces(root=kbroot)
    assert searches == []
    assert any("meta" in w for w in warns)


def test_read_skips_future_schema(kbroot):
    _write(kbroot, "2026-01-02.jsonl", [{"kind": "meta", "schema": 99}, _ev(9)])
    searches, _, warns = trace.read_traces(root=kbroot)
    assert searches == []
    assert any("schema" in w for w in warns)


def test_read_survives_nonnumeric_meta_schema(kbroot):
    """§47 回归(第四十七轮): meta 行也是不可信输入——schema='v2' 曾让 int()
    抛 ValueError 打崩整个 read_traces(stats/feed/callers 三端点全挂, 与事件行
    崩同半径); meta 行是 JSON 数组时 .get 抛 AttributeError 同崩。修复: 非数值
    schema 按本地兼容读取+warn, 非对象 meta 行按缺失跳过。"""
    _write(kbroot, "2026-01-03.jsonl", ['{"kind": "meta", "schema": "v2"}', _ev(1)])
    searches, _, warns = trace.read_traces(root=kbroot)
    assert [s["trace_id"] for s in searches] == ["t-1"]  # 兼容读取不丢事件
    assert any("非数值" in w for w in warns)


def test_read_survives_meta_line_non_dict(kbroot):
    _write(kbroot, "2026-01-04.jsonl", ["[1, 2]", _ev(2)])
    searches, _, warns = trace.read_traces(root=kbroot)
    assert searches == []
    assert any("meta" in w for w in warns)


def test_read_skips_bad_line_and_warns(kbroot):
    _write(kbroot, f"{dt.date.today():%Y-%m-%d}.jsonl",
           [{"kind": "meta", "schema": 1}, _ev(1), "{ broken json", _ev(2)])
    searches, _, warns = trace.read_traces(root=kbroot)
    assert {s["trace_id"] for s in searches} == {"t-1", "t-2"}
    assert any("bad line" in w for w in warns)


def test_read_coerces_dirty_types_and_warns(kbroot):
    """§26 回归: 脏类型(null/非列表 returned/非数值 chars)解析期归一, 不再让 stats 崩。"""
    bad_ret, bad_chars = _ev(2), _ev(3)
    bad_ret["returned"] = "abc"
    bad_chars["returned_chars"] = "xyz"
    _write(kbroot, f"{dt.date.today():%Y-%m-%d}.jsonl",
           [{"kind": "meta", "schema": 1}, dict(_ev(1), returned=None),
            bad_ret, bad_chars, "[1,2,3]", '"bare"'])
    searches, _, warns = trace.read_traces(root=kbroot)
    by = {s["trace_id"]: s for s in searches}
    assert by["t-1"]["returned"] == []                 # 显式 null → 零命中
    assert by["t-2"]["returned"] == []                 # 非列表 → 零命中 + 告警
    assert by["t-3"]["returned_chars"] is None         # 非数值 → 不计入
    assert any("returned 非列表" in w for w in warns)
    assert any("chars 非数值" in w for w in warns)
    from kb import stats
    stats.aggregate(searches, [])                      # 归一后聚合不再 TypeError


def test_read_coerces_all_list_fields(kbroot):
    """§50 回归: 当年只归一 returned, `layers: null` 同样炸 stats.top_consumed
    (`.get(k, [])` 对"键存在但为 null"不生效)。所有列表字段统一解析期归零。"""
    from kb import stats
    ev = dict(_ev(9), returned=[])
    for k in ("layers", "ext", "suggest", "read"):
        ev[k] = None
    ev2 = dict(_ev(10), returned=[])
    ev2["layers"] = "not-a-list"
    _write(kbroot, f"{dt.date.today():%Y-%m-%d}.jsonl",
           [{"kind": "meta", "schema": 1}, ev, ev2])
    searches, _, warns = trace.read_traces(root=kbroot)
    by = {s["trace_id"]: s for s in searches}
    for k in ("layers", "ext", "suggest", "read"):
        assert k not in by["t-9"]                       # 显式 null → 视作缺失
    assert "layers" not in by["t-10"]                   # 非列表 → 剔除 + 告警
    assert any("layers 非列表" in w for w in warns)
    stats.top_consumed(searches, [])                    # 曾经正是这里 TypeError
    stats.feed_events(searches, [])
    stats.by_source(searches)


def test_read_coerces_query_types(kbroot):
    """§55: query 是检索词不是身份——数值(agent 查 "123" 被 JSON 化成 123)转
    字符串保留语义; 容器(list 不可哈希/dict)删键。消费方 top_queries 做 Counter
    键、zero_hit_board 调 .strip(), 修复前实测双双崩。"""
    from kb import stats
    ev1 = dict(_ev(21), returned=[], query=123)
    ev2 = dict(_ev(22), returned=[], query=["a", "b"])
    _write(kbroot, f"{dt.date.today():%Y-%m-%d}.jsonl",
           [{"kind": "meta", "schema": 1}, ev1, ev2])
    searches, _, warns = trace.read_traces(root=kbroot)
    by = {s["trace_id"]: s for s in searches}
    assert by["t-21"]["query"] == "123"                 # 标量转字符串
    assert "query" not in by["t-22"]                    # 容器删键
    assert any("query" in w for w in warns)
    stats.top_queries(searches)
    stats.zero_hit_board(searches)


def test_read_filters_and_ordering(kbroot):
    for i, caller in enumerate(["web", "algo", "web"]):
        ev = _ev(i, caller=caller, returned=())
        ev["ts"] = f"2026-10-1{i + 1}T10:00:00+08:00"
        trace.append_event(ev, root=kbroot)
    by_caller, _, _ = trace.read_traces(root=kbroot, caller="web")
    assert [s["trace_id"] for s in by_caller] == ["t-2", "t-0"]   # 最新在前
    zero, _, _ = trace.read_traces(root=kbroot, zero_hit=True)
    assert len(zero) == 3                                        # 三条 returned 均空
    limited, _, _ = trace.read_traces(root=kbroot, limit=2)
    assert len(limited) == 2
    since, _, _ = trace.read_traces(root=kbroot, since="2026-10-13")
    assert {s["trace_id"] for s in since} == {"t-2"}


def test_read_limit_nonpositive_is_zero_slots(kbroot):
    """§58(第四十轮): Python 切片 `[:-2]` 是"去尾两个"——`--limit -2` 曾返回
    全量减 2 条("要最少给最多"翻转语义)。≤0 一律零名额, None 才是"不限"。"""
    for i in range(3):
        trace.append_event(_ev(i, caller="web"), root=kbroot)
    for bad in (0, -2):
        limited, _, _ = trace.read_traces(root=kbroot, limit=bad)
        assert limited == []
    full, _, _ = trace.read_traces(root=kbroot, limit=None)
    assert len(full) == 3


def test_find_and_latest_search_id(kbroot):
    for i in range(3):
        ev = _ev(i, caller="web")
        ev["ts"] = f"2026-10-15T14:32:0{i+1}+08:00"   # 递增 ts, 排序可断言
        trace.append_event(ev, root=kbroot)
    assert trace.find_trace("t-1", root=kbroot)["query"] == "q1"
    assert trace.find_trace("nope", root=kbroot) is None
    assert trace.latest_search_id("web", root=kbroot) == "t-2"
    assert trace.latest_search_id("other", root=kbroot) is None


def test_latest_search_id_prefers_search_that_returned_the_id(kbroot):
    """§40: 多轮检索后读早轮返回的条目, 应关联到**返回过它**的那次 search,
    而非盲目取最近一次。旧实现挂错 trace → _consumed_ids 判未消费 → 头条
    consume_rate 系统性偏低。"""
    a = _ev(1, caller="web", returned=("k1", "k2"))
    a["ts"] = "2026-10-15T14:00:01+08:00"
    b = _ev(2, caller="web", returned=("k3",))          # 最近一次, 但不含 k1
    b["ts"] = "2026-10-15T14:00:02+08:00"
    for ev in (a, b):
        trace.append_event(ev, root=kbroot)
    # 精确匹配: get("k1") 挂回返回过 k1 的 t-1, 不是最近的 t-2
    assert trace.latest_search_id("web", root=kbroot, entry_id="k1") == "t-1"
    assert trace.latest_search_id("web", root=kbroot, entry_id="k3") == "t-2"
    # 消费判定闭环: 挂对 trace 后 k1 计入消费集
    from kb import stats
    S = [a, b]
    g = {"kind": "get", "trace_id": trace.latest_search_id(
        "web", root=kbroot, entry_id="k1"), "id": "k1", "ok": True}
    assert stats._consumed_ids(S, [g]) == {"k1"}
    # 回退: 关联不到(如外接源 id / 手动 get)时退回纯最近一次, 不返回 None
    assert trace.latest_search_id("web", root=kbroot, entry_id="nope") == "t-2"
    assert trace.latest_search_id("web", root=kbroot) == "t-2"  # 不传 entry_id 保持旧语义
