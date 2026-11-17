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
    # 公开版对端 ROUTES=['code','model','you'], routes 多一个键都会被
    # normalizeConfig 拒(Unknown configuration field)——2026-11-11 线上实测。
    assert labels == {"项目层命中", "通用层命中", "已读消费"}
    # layout 白名单以当前挂载对端为准: 公开版只认 portrait/landscape/square
    assert rec["config"]["layout"] == "landscape"


def test_spider_id_sanitizes_and_roundtrips():
    import re
    ok = re.compile(r"^[\w.:-]+$", re.UNICODE)
    # source:// 原生 id 含 '/', 对端正则会拒(真机校准) → '/'归一为'-', ':'与'.'保留
    assert spider_export.spider_id("source://tdbm/wiki/redis.md") == "source:--tdbm-wiki-redis.md"
    assert ok.match(spider_export.spider_id("source://tdbm/wiki/redis.md"))
    # 普通 kb id 原样保留(search/get 两侧同函数, you 匹配不断)
    assert spider_export.spider_id("kb-20261012-7f3a") == "kb-20261012-7f3a"


def test_get_without_id_key_does_not_crash_consumed():
    """§55 同函数第二行回归(第四十八轮): read_ids 有 isinstance 守卫而 consumed
    裸取 g["id"]——净化删过 id 键的 get(§52)遇 returned 里的 null 元素时
    `None in returned` 判真 → KeyError 掐断回放(/api/replay 与 /api/spider 500)。"""
    tr = _trace()
    tr["trace_id"] = None
    tr["returned"] = ["kb-a", None]
    gets = [{"kind": "get", "trace_id": None, "ts": "2026-10-15T14:33:00+08:00",
             "caller_repo": "flysee_video_web", "ok": True}]  # id 键已被净化删除
    rec = spider_export.to_record(tr, gets)   # 修复前: KeyError 'id'
    assert rec["consumed"] == []


def test_ext_hits_are_model_route_and_sanitized():
    """外接源命中: 公开版对端无 ext 分支(validateEvent 只认 code/model/you),
    并入 model 分支, 区分信息留在 label 的"外接 <源>: "前缀。"""
    tr = _trace()
    tr["returned"] = ["kb-a", "source://tdbm/wiki/redis.md"]
    tr["ext"] = [{"source": "tdbm", "ok": True, "hits": ["source://tdbm/wiki/redis.md"]}]
    rec = spider_export.to_record(tr, _gets())
    by_id = {e["id"]: e for e in rec["events"]}
    sid = "source:--tdbm-wiki-redis.md"
    assert by_id[sid]["route"] == "model"
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


def test_timeline_staggered_not_all_at_once():
    """gif 节奏回归守护: 命中不得再全挤 0.5/1.5 两点(动画 1s 闪完=蜘蛛空转);
    逐条 running 必须错开, 且每条先 running 后 completed。stagger<fly 交错时
    仍须 at 非递减(排序后编 revision)。"""
    tr = _trace()
    ids = [f"kb-{i}" for i in range(12)]
    tr["returned"] = ids
    tr["layers"] = [{"repo": "docs", "scanned": 40, "rejected": {"filter": 0, "query": 28},
                     "matched": [{"id": i, "title": f"t{i}", "scope": "project",
                                   "confidence": "verified", "hit_fields": ["title"],
                                   "hit_spans": [[0, 1]], "rank": n}
                                  for n, i in enumerate(ids)],
                     "taken": 12, "truncated_at_limit": False}]
    rec = spider_export.to_record(tr, [])
    log = rec["log"]
    assert all(b["at"] >= a["at"] for a, b in itertools.pairwise(log))
    run_at = [e["at"] for e in log if e["type"] == "events"
              and e["events"][0]["status"] == "running"]
    assert len(run_at) == 12
    assert len(set(run_at)) >= 8          # 至少大部分错开(round 到 0.01s 可同刻)
    assert run_at == sorted(run_at)
    first, last = min(run_at), max(run_at)
    assert last - first >= 6.0            # 12 条按上限 0.6s 错开 ≈6.6s
    assert rec["duration"] <= 14.5        # 封顶: 不至于久等
    assert rec["duration"] == log[-1]["at"]


def test_timeline_zero_and_all_you_short_loop():
    """零命中/全已读是静帧展示, 无动画可看 → 短循环不让人等。"""
    tr = _trace()
    tr["layers"] = [{**tr["layers"][0], "matched": [], "taken": 0}]
    tr["returned"] = []
    assert spider_export.to_record(tr, [])["duration"] == spider_export._ZERO_END
    rec = spider_export.to_record(_trace(), _gets())   # kb-a you + kb-b model 非全 you
    tr2 = _trace()
    tr2["returned"] = ["kb-a"]
    rec2 = spider_export.to_record(tr2, _gets())       # 唯一命中即 you → 全 you 短轴
    assert rec2["duration"] == spider_export._ZERO_END
    assert any(e["type"] == "events" for e in rec2["log"])   # you 仍要入 log, 不能丢
    assert rec["duration"] > spider_export._ZERO_END


def test_zero_hit_trace_valid():
    tr = _trace()
    tr["layers"] = [{**tr["layers"][0], "matched": [], "taken": 0}]
    tr["returned"] = []
    rec = spider_export.to_record(tr, [])
    assert rec["events"] == []
    assert "0 命中" in rec["config"]["subtitle"]


def test_dirty_trace_survives_hard_index_sweep():
    """§55 实锤: _coerce 对非字符串身份字段**删键**, 硬索引消费方成雷区——
    get 缺 id → g["id"] KeyError; search 缺 trace_id → search_ev["trace_id"]
    KeyError, 回放屏整个掐断。尽力呈现消费方必须缺键跳过而非炸。"""
    tr = _trace()
    gets = _gets()
    gets[0].pop("id")                       # 模拟净化删键后的 get
    rec = spider_export.to_record(tr, gets)  # 旧: KeyError 'id'
    assert rec["consumed"] == []             # 缺 id 的 get 不再认领消费
    tr2 = _trace()
    tr2.pop("trace_id")                      # 模拟净化删键后的 search
    rec2 = spider_export.to_record(tr2, _gets())  # 旧: KeyError 'trace_id'
    assert rec2["id"] == ""
    tr3 = _trace()
    tr3["layers"][0]["matched"][0].pop("id")     # matched 子项缺 id(不在净化名单)
    rec3 = spider_export.to_record(tr3, _gets())
    assert [e["id"] for e in rec3["events"]] == ["kb-b"]   # 坏项跳过, 好项保留
    tr4 = _trace()
    tr4["layers"].append("not-a-dict")                 # 层本身非 dict
    rec4 = spider_export.to_record(tr4, _gets())
    assert len(rec4["events"]) == 2                    # subtitle/truncated 均不再炸


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


def test_sparse_legacy_trace_no_crash():
    """手工构造/早期 schema 的 trace: matched 可缺 title, rejected 可缺 filter/query。
    实测踩坑: serve /api/replay|spider 遇此形态 KeyError 直接掐连接(浏览器只见 Failed to fetch)。"""
    tr = {"kind": "search", "trace_id": "trc-sparse", "ts": "2026-10-21T10:00:00",
          "caller_repo": "agent-kb", "source": "cli", "query": "稀疏验证",
          "returned": ["kb-1"], "duration_ms": 5,
          "layers": [{"repo": "agent-kb", "scanned": 10,
                      "rejected": {"query": 9},          # 无 filter 键
                      "matched": [{"id": "kb-1", "hit_fields": ["title"]}]}]}  # 无 title 键
    rec = spider_export.to_record(tr, [])
    assert rec["events"][0]["label"] == "kb-1"           # 缺 title 回退 id
    assert "agent-kb" in rec["config"]["subtitle"]


def test_zero_hit_layer_without_matched_key():
    """零命中层可整键缺 matched(仿真脚本/手工 trace 常见形态: 只记 scanned/rejected)。
    实测踩坑(第九轮走查): to_record 裸取 layer["matched"] → 桥内 KeyError → 降级。"""
    tr = {"kind": "search", "trace_id": "trc-zh", "ts": "2026-10-22T10:00:00",
          "caller_repo": "agent-kb", "source": "cli", "query": "全淘汰",
          "returned": [], "duration_ms": 5, "limit": 20,
          "layers": [{"repo": "pg-proj", "scanned": 40, "rejected": {"filter": 25, "query": 15}}]}
    rec = spider_export.to_record(tr, [])
    assert rec["events"] == []
    assert "0 命中" in rec["config"]["subtitle"]
    assert "pg-proj 扫描40" in rec["config"]["subtitle"]


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


# ---- 逐词归因记录(word unit): 真实查询 token 级事实源 --------------------

def _word_trace(**over):
    """查询 3 token: vite 命中项目层, kb-b 只命中通用层, 不存在词零命中。"""
    t = _trace()
    t["query"] = "vite kb-b 不存在词"
    t["layers"][0]["matched"] = [{"id": "kb-a", "title": "vite hmr DOM 失效",
                                  "hit_tokens": ["vite"], "rank": 1}]
    t["layers"][1]["matched"] = [{"id": "kb-b", "title": "keep-alive SSE",
                                  "hit_tokens": ["kb-b"], "rank": 1}]
    t["returned"] = ["kb-a", "kb-b"]
    t.update(over)
    return t


def test_word_record_config_and_token_indices():
    rec = spider_export.to_word_record(_word_trace(), [])
    cfg = rec["config"]
    assert cfg["unit"] == "word"
    assert cfg["prompt"] == "vite kb-b 不存在词"      # 与上游 \S+ 重算的分词逐一对齐
    assert set(cfg["routes"]) == {"code", "model", "you"}   # 公开版路由白名单
    evs = rec["events"]
    # 零命中词(不存在词)不产生事件(见 route_attribution 用例的路由计数取证),
    # 有证据的词才成腿, tokenIndex 仍指向它在 prompt 分词里的真实位置。
    assert [e["tokenIndex"] for e in evs] == [0, 1]
    assert [e["label"] for e in evs] == ["vite", "kb-b"]


def test_word_record_route_attribution_is_per_token_evidence():
    # you=该词的命中条目被本 trace 读过; code=项目层; model=通用层
    gets = [{"kind": "get", "trace_id": "t-1", "ts": "2026-10-15T14:33:00+08:00",
             "source": "mcp", "caller_repo": "x", "id": "kb-b", "layer": "kb",
             "ok": True}]
    rec = spider_export.to_word_record(_word_trace(), gets)
    by_idx = {e["tokenIndex"]: e for e in rec["events"]}
    assert by_idx[0]["route"] == "code"          # vite → 仅项目层命中
    assert by_idx[1]["route"] == "you"           # kb-b → 命中条目已读
    # 对端路由计数(live-renderer counts[route])只按 route 累加、不看 status,
    # 给零命中词挂任何一条路由事件都会把"项目层命中"数字虚增成含未命中词
    # → 零命中词不入 events(蜘蛛不抓它=提示词上不高亮), 改由副标题显式点名。
    assert 2 not in by_idx
    assert "零命中词: 不存在词" in rec["config"]["subtitle"]


def test_word_record_model_layer_route():
    # 只命中通用层(kb 层)的词 → model; 同词跨两层时项目层优先(code)
    tr = _word_trace()
    tr["layers"][0]["matched"] = []
    tr["layers"][1]["matched"] = [{"id": "kb-b", "title": "keep-alive SSE",
                                   "hit_tokens": ["vite", "kb-b"], "rank": 1}]
    by_idx = {e["tokenIndex"]: e
              for e in spider_export.to_word_record(tr, [])["events"]}
    assert by_idx[0]["route"] == "model"
    assert by_idx[1]["route"] == "model"


def test_word_record_score_is_always_null():
    # 归因是确定性集合关系, 不是概率; 编 P 值=重回演示数据的造假路线
    for e in spider_export.to_word_record(_word_trace(), [])["events"]:
        assert e["score"] is None


def test_word_record_zero_hit_search_lists_every_token():
    # 整条检索零命中: 无 events 可挂(挂了就是虚增命中数), 全部词进副标题
    tr = _word_trace()
    tr["layers"] = [{"repo": "docs", "scanned": 208,
                     "rejected": {"filter": 0, "query": 208}, "matched": []}]
    tr["returned"] = []
    rec = spider_export.to_word_record(tr, [])
    assert rec["events"] == []
    sub = rec["config"]["subtitle"]
    assert "命中词 0/3" in sub and "vite" in sub and "不存在词" in sub
    assert rec["log"][0]["type"] == "configure" and rec["log"][-1]["type"] == "complete"


def test_word_record_refuses_traces_without_attribution():
    # 旧 trace(matched 无 hit_tokens)无法归因 → 显式拒绝, 绝不"全词算命中"式反猜
    with pytest.raises(ValueError, match="逐词归因"):
        spider_export.to_word_record(_trace(), _gets())


def test_word_record_refuses_empty_query():
    tr = _word_trace(query="   ")
    with pytest.raises(ValueError, match="查询词"):
        spider_export.to_word_record(tr, [])


def test_word_record_log_contract_matches_upstream():
    rec = spider_export.to_word_record(_word_trace(), [])
    log = rec["log"]
    assert [e["revision"] for e in log] == list(range(1, len(log) + 1))
    assert all(b["at"] >= a["at"] for a, b in itertools.pairwise(log))
    assert log[0]["type"] == "configure" and log[-1]["type"] == "complete"
    assert rec["duration"] == log[-1]["at"]
    assert rec["status"] == "completed"
    # 对端: word 会话每个事件的 tokenIndex 必须在 prompt 分词界内
    n = len("vite kb-b 不存在词".split())
    assert all(0 <= e["tokenIndex"] < n for e in rec["events"])


def test_word_record_same_token_across_multiple_entries(tmp_path):
    """真 trace 实测(2026-11-16 t-20261116-ce4c): 两条命中条目共享同一查询词时,
    best 归并分支对 tuple 做 cur[0]= 赋值 TypeError → /api/spider?unit=word 500。
    单测此前每词只喂一条命中, 归并分支从未被走到。"""
    t = _word_trace()
    t["query"] = "vite kb-b"
    t["layers"][0]["matched"] = [
        {"id": "kb-a", "title": "vite hmr DOM 失效", "hit_tokens": ["vite"], "rank": 1},
        {"id": "kb-c", "title": "vite 别名踩坑", "hit_tokens": ["vite"], "rank": 2}]
    t["layers"][1]["matched"] = [{"id": "kb-b", "title": "keep-alive SSE",
                                  "hit_tokens": ["kb-b"], "rank": 1}]
    t["returned"] = ["kb-a", "kb-b", "kb-c"]
    rec = spider_export.to_word_record(t, [])
    ev = next(e for e in rec["events"] if e["label"] == "vite")
    assert "2 条" in ev["detail"]                # 两条证据并入同一词腿
    assert ev["route"] == "code"                 # 跨层取最贴近项目层的归因不变
