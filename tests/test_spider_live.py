"""FR-2.4 spider-live 的纯映射回归(不依赖 Node)。"""
from kb.spider_live import event_to_updates
import pytest


def _search():
    return {"kind": "search", "trace_id": "t1", "caller_repo": "web",
            "query": "vite", "returned": ["p1", "g1", "d1"],
            "layers": [
                {"repo": "docs", "scanned": 5, "rejected": {"filter": 0, "query": 4},
                 "matched": [{"id": "p1", "title": "项目坑", "hit_fields": ["title"]},
                             {"id": "g1", "title": "通用坑", "hit_fields": ["tags"]}],
                 "taken": 2, "truncated_at_limit": False},
            ],
            "ext": [{"source": "demo", "ok": True, "hits": ["d1"]}]}


def test_route_mapping_three_branches():
    cfg, events = event_to_updates(_search())
    by = {e["id"]: e for e in events}
    assert by["p1"]["route"] == "code"   # 首层=项目层(docs) 全部 code 绿
    assert by["g1"]["route"] == "code"
    assert by["d1"]["route"] == "ext"    # 外接源 → ext 粉(B-1 独立分支)
    assert cfg["routes"]["ext"]["color"] == "#F34A87"  # PRD FR-5.2 指定色
    assert cfg["routes"]["you"]["color"] == "#F0CA57"  # 已读消费=you 黄(由 get 事件驱动)


def test_layers_outcome_first_layer_is_project():
    cfg, events = event_to_updates(_search())
    by = {e["id"]: e for e in events}
    assert by["p1"]["route"] == "code" and by["g1"]["route"] == "code"


def test_two_layers_route_by_layer():
    ev = _search()
    ev["layers"].append({"repo": "kb", "scanned": 3,
                         "rejected": {"filter": 0, "query": 2},
                         "matched": [{"id": "u1", "title": "栈层", "hit_fields": ["summary"]}],
                         "taken": 1, "truncated_at_limit": False})
    ev["returned"].append("u1")
    _, events = event_to_updates(ev)
    by = {e["id"]: e for e in events}
    assert by["u1"]["route"] == "model"          # 第二层(通用层) → model


def test_zero_hit_session_has_subtitle_hint():
    ev = _search()
    ev["returned"], ev["layers"][0]["matched"], ev["ext"] = [], [], []
    cfg, events = event_to_updates(ev)
    assert events == [] and "0 命中" in cfg["subtitle"]


def test_titles_truncated_to_40():
    ev = _search()
    ev["layers"][0]["matched"][0]["title"] = "长" * 60
    _, events = event_to_updates(ev)
    assert len(next(e for e in events if e["id"] == "p1")["label"]) <= 40


def test_find_spider_home_missing_raises(monkeypatch):
    from kb import spider_live
    monkeypatch.setattr(spider_live, "COMMON_HOMES", [])
    with pytest.raises(FileNotFoundError):
        spider_live.find_spider_home(r"Z:\不存在的目录")


# ---- 第二十八轮走查(§46): run 增量读取的 tail 语义 + 脏事件不崩直播 ------

def test_event_to_updates_tolerates_null_fields():
    """手工/异客户端 trace 的 returned/layers/ext 可显式为 null: .get 默认值对
    "键存在但为 null"不生效, 曾让 _dispatch 抛 TypeError(逐事件防护前 = 崩直播)。"""
    ev = {"kind": "search", "trace_id": "x1", "caller_repo": "p", "query": "q",
          "returned": None, "layers": None, "ext": None}
    cfg, events = event_to_updates(ev)   # 不抛
    assert events == [] and "0 命中" in cfg["subtitle"]


def test_run_replays_line_completed_after_partial(tmp_path, monkeypatch):
    """§46 实锤: 旧实现 `offsets[f]=fh.tell()` 推进越过半行字节, 行补全后视为已
    消费 → 该事件在直播流永久漏播(第十二轮 serve watcher 同款, 当时未同步这里)。
    tail 语义修复后: 半行不消费, 补全后的下次轮询必须补播。"""
    import json
    import threading
    import time

    from kb import spider_live

    traces = tmp_path / "traces"
    traces.mkdir()
    f = traces / "2026-10-22.jsonl"
    f.write_text(json.dumps({"kind": "meta", "schema": 2}) + "\n", encoding="utf-8")

    calls = []

    class FakeMcp:
        p = None

        def tool(self, name, args):
            calls.append(name)
            return {"id": "s1", "previewUrl": "http://x/"}

        def close(self):
            pass

    monkeypatch.setattr(spider_live, "SpiderMcp", lambda home: FakeMcp())
    monkeypatch.setattr(spider_live, "find_spider_home",
                        lambda explicit=None: tmp_path)
    t = threading.Thread(target=spider_live.run, args=(tmp_path,),
                         kwargs={"max_sec": 2.5}, daemon=True)
    t.start()
    time.sleep(0.3)                      # 让 run 首 tick 登记文件偏移
    line = json.dumps({"kind": "search", "trace_id": "half-1",
                       "ts": "2026-10-22T13:00:00+08:00", "caller_repo": "p",
                       "query": "半行", "returned": [], "duration_ms": 1,
                       "limit": 20, "layers": []}, ensure_ascii=False)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(line[: len(line) // 2])          # 半行
    time.sleep(0.9)
    assert "spider_create_session" not in calls   # 半行不得消费
    with f.open("a", encoding="utf-8") as fh:
        fh.write(line[len(line) // 2:] + "\n")    # 补全
    time.sleep(0.9)
    assert "spider_create_session" in calls       # 补全后必须补播(旧实现在此永久漏播)
    t.join(timeout=5)


def test_run_does_not_replay_pre_existing_history(tmp_path, monkeypatch):
    """§46: 首见文件的 birth 判定曾是 `st_ctime >= time.monotonic()` —— epoch 秒
    与 monotonic 秒不同钟系恒 False → 每次启动把所有历史 trace 从头回放(会话洪泛)。"""
    import json
    import threading

    from kb import spider_live

    traces = tmp_path / "traces"
    traces.mkdir()
    # 启动前就存在的历史文件(含一条完整事件)
    (traces / "2026-10-01.jsonl").write_text(
        json.dumps({"kind": "meta", "schema": 2}) + "\n" + json.dumps(
            {"kind": "search", "trace_id": "old-1",
             "ts": "2026-10-01T10:00:00+08:00", "caller_repo": "p",
             "query": "历史", "returned": [], "duration_ms": 1,
             "limit": 20, "layers": []}, ensure_ascii=False) + "\n",
        encoding="utf-8")

    calls = []

    class FakeMcp:
        p = None

        def tool(self, name, args):
            calls.append(name)
            return {"id": "s1", "previewUrl": "http://x/"}

        def close(self):
            pass

    monkeypatch.setattr(spider_live, "SpiderMcp", lambda home: FakeMcp())
    monkeypatch.setattr(spider_live, "find_spider_home",
                        lambda explicit=None: tmp_path)
    t = threading.Thread(target=spider_live.run, args=(tmp_path,),
                         kwargs={"max_sec": 1.5}, daemon=True)
    t.start()
    t.join(timeout=5)
    assert calls == []                   # 历史事件不得回灌


def test_run_survives_poisoned_line(tmp_path, monkeypatch):
    """脏事件(桥工具抛异常)只跳过该条, 直播循环必须续跑到后续好事件。"""
    import json
    import threading
    import time

    from kb import spider_live

    traces = tmp_path / "traces"
    traces.mkdir()
    f = traces / "2026-10-22.jsonl"
    f.write_text(json.dumps({"kind": "meta", "schema": 2}) + "\n", encoding="utf-8")

    calls = []

    class SelectiveMcp:
        p = None

        def tool(self, name, args):
            calls.append(name)
            if name == "spider_create_session" and args["config"]["prompt"] == "毒":
                raise RuntimeError("桥炸了(模拟)")
            return {"id": "s1", "previewUrl": "http://x/"}

        def close(self):
            pass

    monkeypatch.setattr(spider_live, "SpiderMcp", lambda home: SelectiveMcp())
    monkeypatch.setattr(spider_live, "find_spider_home",
                        lambda explicit=None: tmp_path)
    t = threading.Thread(target=spider_live.run, args=(tmp_path,),
                         kwargs={"max_sec": 2.0}, daemon=True)
    t.start()
    time.sleep(0.3)
    with f.open("a", encoding="utf-8") as fh:
        for tid, q in (("bad", "毒"), ("good", "好")):
            fh.write(json.dumps({"kind": "search", "trace_id": tid,
                                 "ts": "2026-10-22T13:00:00+08:00",
                                 "caller_repo": "p", "query": q, "returned": [],
                                 "duration_ms": 1, "limit": 20,
                                 "layers": []}, ensure_ascii=False) + "\n")
    time.sleep(0.9)
    n = calls.count("spider_create_session")
    assert n >= 2                        # 毒事件后的"好"事件仍被直播(未被崩退带走)
    t.join(timeout=5)


# ---- 第五十八轮走查(§75): _dispatch get 分支对净化可删键的同口径守卫 ------

def test_dispatch_get_branch_survives_stripped_id():
    """§66 同函数两分支: search 分支经 event_to_updates 有 isinstance 守卫,
    get 分支曾裸取 ev["id"]——§52 净化把非字符串 id 删键后 KeyError(被 run
    循环吞掉 = 该条已读标注静默丢播)。修复后: 坏事件安全跳过, 好事件照常发。"""
    from kb.spider_live import _dispatch
    from kb.trace import _coerce

    class RecMcp:
        def __init__(self):
            self.calls = []

        def tool(self, name, args):
            self.calls.append((name, args))
            return {"id": "s1"}

    mcp = RecMcp()
    active = {"t1": {"session": "s1", "last": 0.0, "has_hits": True}}

    bad = {"kind": "get", "trace_id": "t1", "caller_repo": None,
           "id": 12345, "ok": True}
    _coerce(bad, [], "test.jsonl")            # §52 净化: 非字符串 id → 删键
    _dispatch(mcp, bad, active, None)          # 不得 KeyError
    assert mcp.calls == []                     # 坏事件不发标注

    good = {"kind": "get", "trace_id": "t1", "caller_repo": None,
            "id": "kb-20261012-7f3a", "ok": True}
    _coerce(good, [], "test.jsonl")            # 合法 id 原样保留
    _dispatch(mcp, good, active, None)
    assert mcp.calls and mcp.calls[0][0] == "spider_update_events"
    ev0 = mcp.calls[0][1]["events"][0]
    assert ev0["route"] == "you" and ev0["status"] == "completed"
