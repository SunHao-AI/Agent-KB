"""FR-1.2 指标口径唯一实现(kb.stats)的口径回归 + serve 服务端点冒烟。"""
import datetime as dt
import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from kb import serve, stats


def _search(tid, caller, query, returned, *, ts="2026-10-18T10:00:00+08:00",
            rc=None, suggest=None):
    ev = {"kind": "search", "trace_id": tid, "ts": ts, "source": "mcp",
          "caller_repo": caller, "query": query, "returned": returned,
          "layers": [{"repo": "docs", "scanned": 5,
                      "rejected": {"filter": 0, "query": 5 - len(returned)},
                      "matched": [{"id": i, "title": f"T{i}"} for i in returned],
                      "taken": len(returned), "truncated_at_limit": False}]}
    if rc is not None:
        ev["returned_chars"] = rc
    if suggest:
        ev["suggest"] = suggest
    return ev


def _get(tid, id, caller, *, ok=True, chars=800, ts="2026-10-18T10:00:05+08:00"):
    ev = {"kind": "get", "trace_id": tid, "ts": ts, "source": "mcp",
          "caller_repo": caller, "id": id, "layer": "docs", "ok": ok}
    if chars is not None:
        ev["chars"] = chars
    return ev


def test_hit_rate_and_consume_rate():
    S = [_search("t1", "a", "vite", ["k1", "k2"]),
         _search("t2", "a", "死锁", []),
         _search("t3", "b", "nginx", ["k3"])]
    G = [_get("t1", "k1", "a")]
    k = stats.aggregate(S, G)
    assert k["searches"] == 3
    assert k["hit_rate"] == round(2 / 3, 4)
    assert k["returned_total"] == 3 and k["consumed_total"] == 1
    assert k["consume_rate"] == round(1 / 3, 4)


def test_saved_chars_est_only_when_both_known():
    S = [_search("t1", "a", "v", ["k1", "k2"], rc=400),      # 已知
         _search("t2", "a", "v", ["k3"])]                     # 无 rc(schema=1)
    G = [_get("t1", "k1", "a", chars=1000),                   # 1000-400//2=800
         _get("t2", "k3", "a", chars=900)]                    # 未知→跳过
    k = stats.aggregate(S, G)
    assert k["saved_chars_est"] == 800
    assert k["saved_unknown_count"] == 1
    assert k["overhead_chars"] == 400


def test_saved_never_negative():
    S = [_search("t1", "a", "v", ["k1"], rc=5000)]
    G = [_get("t1", "k1", "a", chars=100)]
    assert stats.aggregate(S, G)["saved_chars_est"] == 0


def test_cold_start_flag():
    S = [_search("t1", "a", "v", ["k1"], ts="2026-10-18T10:00:00+08:00")]
    assert stats.aggregate(S, [])["cold_start"] is True


def test_window_filter_by_day():
    S = [_search("t1", "a", "v", ["k1"], ts="2026-10-01T10:00:00+08:00"),
         _search("t2", "a", "v", [], ts="2026-10-10T10:00:00+08:00")]
    k = stats.aggregate(S, [], since="2026-10-05")
    assert k["searches"] == 1 and k["hit_rate"] == 0.0


def test_zero_hit_board_digested():
    S = [_search("t1", "a", "授权 台账", [], ts="2026-10-01T10:00:00+08:00"),
         _search("t2", "a", "授权 台账", [], ts="2026-10-02T10:00:00+08:00"),
         # 后续同 query 命中 → 该 query 标已消化
         _search("t3", "a", "授权 台账", ["k9"], ts="2026-10-03T10:00:00+08:00"),
         _search("t4", "a", "推流 死锁", [], ts="2026-10-04T10:00:00+08:00")]
    board = stats.zero_hit_board(S)
    by_q = {r["query"]: r for r in board}
    assert by_q["授权 台账"]["count"] == 2 and by_q["授权 台账"]["digested"] is True
    assert by_q["推流 死锁"]["digested"] is False


def test_zero_hit_board_digestion_is_time_directional():
    """§35 实测: 旧实现全量预扫不分先后——"先命中后失败"(条目被降级/删除后检索不到)
    的词仍标已消化, 待消化榜漏掉恰恰最该补的词。消化必须只看失败**之后**的命中。"""
    S = [_search("t1", "a", "css slash", ["k1"], ts="2026-10-01T10:00:00+08:00"),
         # 先命中过, 之后反而查不到了 → 现状未解决, 必须回榜待消化
         _search("t2", "a", "css slash", [], ts="2026-10-05T10:00:00+08:00")]
    by_q = {r["query"]: r for r in stats.zero_hit_board(S)}
    assert by_q["css slash"]["digested"] is False
    # 失败之后补库命中 → 已消化(A1 正路径, 见 test_zero_hit_board_digested)
    S2 = [_search("t3", "a", "vite", [], ts="2026-10-01T10:00:00+08:00"),
          _search("t4", "a", "vite 配置", ["k1"], ts="2026-10-02T10:00:00+08:00")]
    by_q2 = {r["query"]: r for r in stats.zero_hit_board(S2)}
    assert by_q2["vite"]["digested"] is True  # 命中 query 分词含失败词也算消化


def test_timestamp_order_is_offset_aware():
    """§37 实测: ts 是带本机偏移的 ISO 串(trace._now = now().astimezone().isoformat),
    旧实现用**字符串**比较时刻——字符串序只在全体同偏移时才等于时刻序。团队态联邦成员
    跨时区上报即失真: 上海 09:00+08(=01:00Z) 与纽约 08:00-05(=13:00Z), 字符串判上海晚,
    真实纽约晚 12h。三处同时错: 实时流排序、最近活跃(掉线检测)、消化方向。"""
    SH = "2026-10-22T09:00:00+08:00"  # 01:00Z
    NY = "2026-10-22T08:00:00-05:00"  # 13:00Z, 真实更晚
    assert SH > NY  # 字符串序失真(记录旧口径为何错)
    S = [_search("t1", "a", "q1", ["i1"], ts=SH),
        _search("t2", "a", "q2", ["i2"], ts=NY)]
    # 1) 实时流: 真实更晚的排第一(旧实现取 t1)
    assert stats.feed_events(S, [])[0]["trace_id"] == "t2"
    # 2) 最近活跃: 取真实更晚的原串(显示保留写入机钟点与偏移)
    assert stats.callers(S)[0]["last_ts"] == NY
    # 3) 消化方向: 命中晚于失败 12h → 已消化(旧实现判未消化)
    S2 = [_search("t3", "a", "vite", [], ts=SH),
          _search("t4", "a", "vite 配置", ["k1"], ts=NY)]
    assert stats.zero_hit_board(S2)[0]["digested"] is True
    # 反向(命中早于失败)仍判未消化; 同偏移场景口径不变
    S3 = [_search("t5", "a", "vite", [], ts=NY),
          _search("t6", "a", "vite 配置", ["k1"], ts=SH)]
    assert stats.zero_hit_board(S3)[0]["digested"] is False
    S4 = [_search("t7", "a", "vite", [], ts="2026-10-01T10:00:00+08:00"),
          _search("t8", "a", "vite 配置", ["k1"], ts="2026-10-02T10:00:00+08:00")]
    assert stats.zero_hit_board(S4)[0]["digested"] is True


def test_stale_flag_is_offset_invariant():
    """掉线判定改用**时刻差**(stats._age_days), 不再用"查看机本地日 − 写入机本地日"
    的日粒度相减(两基准 + 取整, 14d 门槛附近抖一天)。此处断言可移植的不变性:
    同一真实时刻, 无论带哪个偏移都不得翻转 stale。"""
    import datetime as dt
    tz = dt.timezone
    now = dt.datetime.now(tz.utc)
    for off in (tz(dt.timedelta(hours=14)), tz(dt.timedelta(hours=-12))):
        old = (now - dt.timedelta(days=30)).astimezone(off).isoformat()
        fresh = now.astimezone(off).isoformat()
        byc = {r["caller"]: r for r in stats.callers(
            [_search("t1", "old", "q", [], ts=old),
             _search("t2", "fresh", "q", [], ts=fresh)])}
        assert byc["old"]["stale"] is True
        assert byc["fresh"]["stale"] is False
    # 不可解析的 ts: 不判新鲜度(不误报掉线)
    assert stats.callers([_search("t3", "x", "q", [], ts="not-a-date")])[0]["stale"] is False


def test_zero_hit_board_suggest_on_failure_event_is_live_path():
    """§35 实测: build_search_event 旧版从不写 suggest 进事件, stats 却从命中事件读
    s.get("suggest") ——恒 None 的死分支, "按 suggest 改写后命中"路径从未生效。
    修复: suggest 挂在**失败事件**上, 后续命中词撞上 suggest 即判消化。"""
    S = [_search("t1", "a", "长查询 未命中词", [], suggest=["vite", "hmr"],
                 ts="2026-10-01T10:00:00+08:00"),
         # agent 按 suggest 改写后命中(suggest 词本身成为后续 query)
         _search("t2", "a", "vite", ["k1"], ts="2026-10-02T10:00:00+08:00")]
    by_q = {r["query"]: r for r in stats.zero_hit_board(S)}
    assert by_q["长查询 未命中词"]["digested"] is True


def test_zero_hit_board_multi_caller_requires_all_resolved():
    """AND 语义: 同词两个 caller, 任一 caller 最新失败后仍无命中(现状未解决),
    该词必须留在待消化榜——OR 会把 a 的消化误盖到 b 的未解决上。"""
    S = [_search("t1", "a", "灰度 开关", [], ts="2026-10-01T10:00:00+08:00"),
         _search("t2", "b", "灰度 开关", [], ts="2026-10-01T11:00:00+08:00"),
         _search("t3", "a", "灰度 开关", ["k1"], ts="2026-10-02T10:00:00+08:00")]
    by_q = {r["query"]: r for r in stats.zero_hit_board(S)}
    assert by_q["灰度 开关"]["count"] == 2 and by_q["灰度 开关"]["digested"] is False


def test_top_consumed_and_feed():
    S = [_search("t1", "a", "v", ["k1"]), _search("t2", "a", "v", ["k1"])]
    G = [_get("t1", "k1", "a"), _get("t2", "k1", "a")]
    assert stats.top_consumed(S, G, limit=1)[0] == {"id": "k1", "title": "Tk1", "count": 2}
    feed = stats.feed_events(S, G, caller="a", limit=10)
    assert len(feed) == 2 and feed[0]["read"] == ["k1"]
    # details 必须透传 title: 蜘蛛回放命中行显示人类可读标题而非裸 id
    assert feed[0]["details"]["k1"]["title"] == "Tk1"


def test_gets_by_trace_drops_non_str_id():
    """§67(第五十轮): get 事件 id 被净化删键后, _gets_by_trace 裸 add 把 None
    塞进消费集合——top_consumed 遇 `g["id"]` KeyError、feed read 遇 None+str
    混合 sorted TypeError、aggregate consumed_total 虚报。集合元素必须是 str。"""
    S = [_search("t1", "a", "q", ["kb-a", None])]   # returned 含 null 元素
    G = [{"kind": "get", "trace_id": "t1", "source": "mcp",      # id 键被净化删除
          "caller_repo": "a", "ok": True, "ts": "2026-10-18T10:00:05+08:00"},
         _get("t1", "kb-a", "a")]
    assert stats.top_consumed(S, G) == [{"id": "kb-a", "title": "Tkb-a", "count": 1}]
    feed = stats.feed_events(S, G)
    assert feed[0]["read"] == ["kb-a"]   # 混合形态不再 TypeError
    assert stats.aggregate(S, G)["consumed_total"] == 1   # None 不再冒充消费


def test_feed_events_limit_contract_nonpositive():
    """§58 同族第四处(第四十二轮): feed_events limit 负数切片 `[:-2]` 是"去尾"
    语义, `limit=-2` 返回倒数第二条起的全部——"要最少给最多"翻转。修复后 ≤0
    零名额, 与 read_traces / search_layers_report 同契约。"""
    S = [_search(f"t{i}", "a", f"q{i}", [], ts=f"2026-10-2{i}T10:00:00+08:00")
         for i in range(1, 5)]
    assert stats.feed_events(S, [], limit=0) == []
    assert stats.feed_events(S, [], limit=-2) == []   # 旧行为: 返回 t4/t3(全量减 2)
    assert [e["trace_id"] for e in stats.feed_events(S, [], limit=2)] == ["t4", "t3"]


def test_feed_events_offset_cursor():
    """S1: offset 游标——排序后切片 [offset:offset+limit], 与单次 limit 同序同源,
    翻页不重不漏(面板"加载更多"按已载入条数续取)。"""
    S = [_search(f"t{i}", "a", f"q{i}", [], ts=f"2026-10-2{i}T10:00:00+08:00")
         for i in range(1, 6)]                      # 倒序: t5,t4,t3,t2,t1
    p1 = [e["trace_id"] for e in stats.feed_events(S, [], limit=2)]
    p2 = [e["trace_id"] for e in stats.feed_events(S, [], limit=2, offset=2)]
    assert p1 == ["t5", "t4"] and p2 == ["t3", "t2"]
    assert p1 + p2 == ["t5", "t4", "t3", "t2"]      # 无漏无重
    assert [e["trace_id"] for e in stats.feed_events(S, [], limit=2, offset=4)] == ["t1"]
    assert stats.feed_events(S, [], limit=2, offset=99) == []


def test_board_functions_limit_contract_nonpositive():
    """§58 同族(第四十六轮): top_queries/top_consumed/zero_hit_board 三榜单
    与 feed_events 同文件同族却各自漏网——`[:limit]` 负数尾截"要最少给最多"
    翻转。修复后 ≤0 零名额; limit=2 照常截前 2。"""
    S = [_search(f"t{i}", "a", f"q{i}", [f"kb-x{i}"] if i % 2 == 0 else [],
                 ts=f"2026-10-2{i}T10:00:00+08:00") for i in range(1, 6)]
    G = [{"kind": "get", "trace_id": f"t{i}", "ts": f"2026-10-2{i}T10:01:00+08:00",
          "caller_repo": "a", "id": f"kb-x{i}", "ok": True} for i in range(2, 6, 2)]
    for fn, args in ((stats.top_queries, (S,)),
                     (stats.top_consumed, (S, G)),
                     (stats.zero_hit_board, (S,)),
                     (stats.dead_weight, (S, G))):
        assert fn(*args, limit=0) == [], fn
        assert fn(*args, limit=-2) == [], fn   # 旧行为: 全量减 2(尾截翻转)
    assert len(stats.top_queries(S, limit=2)) == 2


def test_dead_weight_ranks_unconsumed_returns():
    """A6: 消费率低的归因榜——被返回但从未同 trace 读全文的条目。
    口径与 _consumed_ids 互补: 被消费过一次的条目绝不该上榜(哪怕同窗口
    其他 trace 没读它), 只被返回 1-2 次的长尾由 min_returned 滤掉。"""
    S = [_search(f"t{i}", "a", f"q{i}", ["kdead", "kalive"]) for i in range(1, 5)]
    G = [_get("t1", "kalive", "a")]          # kalive 被消费过一次
    rows = stats.dead_weight(S, G)
    assert [r["id"] for r in rows] == ["kdead"]
    assert rows[0]["returned"] == 4 and rows[0]["title"] == "Tkdead"
    assert stats.dead_weight(S, G, min_returned=5) == []


def test_usage_by_id_matches_consumed_caliber():
    """Q11: usage_by_id 的 reads 必须与 top_consumed.count 同一判定(被返回且同
    trace 有 ok get), hits 计所有 returned 出现。质量清单的使用度与热门榜对得上,
    否则同屏两处"消费次数"迟早互相打脸。"""
    S = [_search("t1", "a", "q", ["k1", "k2"], ts="2026-10-18T10:00:00+08:00"),
         _search("t2", "a", "q", ["k1"], ts="2026-10-18T10:01:00+08:00")]
    G = [_get("t1", "k1", "a", ts="2026-10-18T10:00:05+08:00")]   # 只 k1 被消费
    u = stats.usage_by_id(S, G)
    assert u["k1"] == {"hits": 2, "reads": 1, "last": "2026-10-18T10:01:00+08:00"}
    assert u["k2"] == {"hits": 1, "reads": 0, "last": "2026-10-18T10:00:00+08:00"}
    # reads 口径与 top_consumed 一致(同 id 同次数)
    tc = {r["id"]: r["count"] for r in stats.top_consumed(S, G)}
    assert {i: v["reads"] for i, v in u.items() if v["reads"]} == tc
    # get 未伴随同 trace 的 returned(未消费)不计 reads
    assert stats.usage_by_id([], [_get("t9", "kx", "a")]) == {}


def test_dead_weight_ignores_non_str_returned():
    """§67 同族: returned 里的 None/非字符串不得进榜(集合语义要求 str)。"""
    S = [_search("t1", "a", "q", ["k1", None, 3])] * 4
    assert [r["id"] for r in stats.dead_weight(S, [])] == ["k1"]


def test_serve_feed_limit_noninteger_rejected_400(tmp_path):
    """§58 同族(第四十二轮): /api/feed?limit=abc 此前被 `int()` 炸成 500
    internal——客户端错误伪装成服务器故障。修复: 入口校验回 400 指明参数;
    负数合法(零名额语义在 stats 层), 数值照常。"""
    srv, base = _serve(tmp_path)
    try:
        for bad in ("abc", "1.5", "1e3"):
            st, body = _get_any(f"{base}/api/feed?limit={bad}")
            assert st == 400 and "limit" in body["error"], bad
        st, body = _get_url(f"{base}/api/feed?limit=2")
        assert st == 200 and isinstance(body, list)
    finally:
        srv.shutdown()
        srv.server_close()


def test_serve_feed_follows_window(tmp_path):
    """A2(2026-11-02): feed 快照此前固定全时最近 N 条, 切窗口 KPI 变、列表不变,
    同屏两口径。修复后 /api/feed 与 /api/stats 同 _within 口径, 且缓存键必须含
    窗口(否则 7 天/全时两份响应互串)。"""
    import datetime as dt
    today = dt.date.today().isoformat()
    old = (dt.date.today() - dt.timedelta(days=40)).isoformat()
    d = tmp_path / "traces"
    rows = [
        {"kind": "search", "trace_id": "t-new", "ts": f"{today}T10:00:00+08:00",
         "source": "cli", "caller_repo": "p", "query": "近", "returned": ["k1"],
         "layers": [{"repo": "docs", "scanned": 5, "matched": [{"id": "k1", "title": "T"}]}]},
        {"kind": "search", "trace_id": "t-old", "ts": f"{old}T10:00:00+08:00",
         "source": "cli", "caller_repo": "p", "query": "远", "returned": [],
         "layers": [{"repo": "docs", "scanned": 5, "matched": []}]},
    ]
    srv, base = _serve(tmp_path)   # _serve 负责建 traces/, 账本随后写入
    lines = [json.dumps({"kind": "meta", "schema": serve.kbtrace.SCHEMA})] + \
        [json.dumps(r, ensure_ascii=False) for r in rows]     # 账本契约: 首行必须是 meta
    (d / "ledger.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        st, body = _get_url(f"{base}/api/feed?since={today}")
        assert st == 200 and [x["trace_id"] for x in body] == ["t-new"]
        st, body = _get_url(f"{base}/api/feed")           # 不设窗口: 两条都在
        assert [x["trace_id"] for x in body] == ["t-new", "t-old"]
        # 缓存互串守卫: 先取窄窗再取全量(同 caller/limit, 仅 since 不同)
        st, body = _get_url(f"{base}/api/feed?since={today}")
        assert [x["trace_id"] for x in body] == ["t-new"]
        # stats 与 feed 同口径: 7 天窗口下两者都只数到 t-new
        st, sb = _get_url(f"{base}/api/stats?since={today}")
        st, fb = _get_url(f"{base}/api/feed?since={today}")
        assert sb["kpi"]["searches"] == len(fb) == 1
        # X-Total-Count: body 被 limit 截断时, 面板仍能拿到窗口内真实总数
        # (否则 7 天窗/全时都被截成 500, 切窗口计数纹丝不动)
        assert _head(f"{base}/api/feed?since={today}&limit=1") == "1"
        assert _head(f"{base}/api/feed?limit=1") == "2"
        assert _head(f"{base}/api/feed?caller=nope&limit=1") == "0"
    finally:
        srv.shutdown()
        srv.server_close()


def test_callers_stale_detection():
    # 新鲜度基准是"距今 >14d = stale", 用固定日历日写死"fresh"必然腐坏:
    # 2026-11-02 起原 ts(2026-10-19)距已超 14 天, 该用例天天挂。改相对今天取值。
    today = dt.date.today()
    fresh = f"{today - dt.timedelta(days=2):%Y-%m-%d}T10:00:00+08:00"
    dead = f"{today - dt.timedelta(days=40):%Y-%m-%d}T10:00:00+08:00"
    S = [_search("t1", "fresh", "v", ["k1"], ts=fresh),
         _search("t2", "dead", "v", ["k1"], ts=dead)]
    rows = {r["caller"]: r for r in stats.callers(S)}
    assert rows["fresh"]["stale"] is False and rows["dead"]["stale"] is True


def test_callers_window_consistency_with_kpi():
    """§29 实测: 窗口按钮只作用 KPI, 同屏矩阵数全量 → 两口径。修复后矩阵统计列
    随窗口; 但活跃性(last_ts/stale)保持全量, 窗口外才活跃的行不得被整行抹掉。"""
    S = [_search("t1", "a", "v", ["k1"], ts="2026-10-18T10:00:00+08:00"),
         _search("t2", "a", "v", ["k2"], ts="2026-09-01T10:00:00+08:00"),
         _search("t3", "ghost", "v", ["k9"], ts="2026-08-01T10:00:00+08:00")]
    win = {r["caller"]: r for r in stats.callers(S, since="2026-10-01")}
    kpi = stats.aggregate(S, [], since="2026-10-01")["by_caller"]
    assert win["a"]["searches"] == kpi["a"]["searches"] == 1      # 统计列与 KPI 同口径
    assert "ghost" in win and win["ghost"]["searches"] == 0       # 窗口外行保留(显 stale)
    assert win["ghost"]["stale"] is True
    assert win["ghost"]["hit_rate"] is None                        # 窗口内 0 次 = —, 非 0%
    assert win["a"]["last_ts"].startswith("2026-10-18")            # 活跃性看全量


def test_boards_honour_time_window():
    """榜单空态文案写着"窗口内", 实现必须真按窗口数(§29)。"""
    S = [_search("t1", "a", "热查询", ["k1"], ts="2026-10-18T10:00:00+08:00"),
         _search("t2", "a", "老零命中", [], ts="2026-08-01T10:00:00+08:00")]
    s_win = stats.in_window(S, "2026-10-01")
    assert stats.top_queries(s_win, limit=10) == [{"query": "热查询", "count": 1}]
    assert stats.zero_hit_board(s_win, limit=10) == []
    assert len(stats.zero_hit_board(S, limit=10)) == 1             # 不带窗口仍数全量


def test_watcher_waits_for_complete_line(tmp_path):
    """§30 第十二轮实测: 观察者读到半行时, 偏移曾推进越过未写完字节, 行补全后
    watcher 视为已消费 → 该事件在 SSE 实时流里永久漏推(文件完整, 刷新才可见)。
    tail 语义修复: 只消费到最后一个换行, 偏移停在行边界等下次轮询。"""
    (tmp_path / "traces").mkdir()
    f = tmp_path / "traces" / "2026-10-22.jsonl"
    f.write_text(json.dumps({"kind": "meta", "schema": 2}) + "\n", encoding="utf-8")
    w = serve.TraceWatcher(tmp_path, quiet=True)
    w._birth = 0.0                     # 视作启动后新文件: 从头播
    q = w.subscribe()
    line = json.dumps({"kind": "search", "trace_id": "half-1", "ts": "2026-10-22T13:00:00",
                       "caller_repo": "p", "query": "半行", "returned": [],
                       "duration_ms": 1, "limit": 20, "layers": []}, ensure_ascii=False)
    w._tick()
    with f.open("a", encoding="utf-8") as fh:
        fh.write(line[: len(line) // 2])      # 半行
    w._tick()
    assert q.empty()                          # 半行不得消费
    with f.open("a", encoding="utf-8") as fh:
        fh.write(line[len(line) // 2:] + "\n")  # 补全
    w._tick()
    assert q.get_nowait()["trace_id"] == "half-1"
    w._tick()
    assert q.empty()                          # 不重复广播
    w.unsubscribe(q)


# ---- serve 端点冒烟(临时目录当仓根, 端口 0 自动分配) ----------------------

def _serve(tmp_path, token=None, default_caller=None):
    # exist_ok: 部分用例要先写账本再拉服务(写文件需要 traces/ 已存在)
    (tmp_path / "traces").mkdir(exist_ok=True)
    srv = serve.ServeServer(("127.0.0.1", 0), tmp_path, token, default_caller, quiet=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    port = srv.server_address[1]
    return srv, f"http://127.0.0.1:{port}"


def _get_url(url, token=None):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, json.loads(r.read().decode())


def _get_any(url):
    """非 2xx 也返回 (status, body), 便于断言 404/503 错误体。"""
    try:
        return _get_url(url)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def test_panel_inline_script_parses(tmp_path):
    """面板内联脚本语法守护(2026-11-02 实测教训): 一处多余的单引号让整段 <script>
    解析失败——389 条 pytest 全绿(后端与数据层确实没坏), 浏览器却整页白屏、
    连接指示器永停"连接中…"。serve 只在启动时读 HTML, 单测又只断言 HTML 含标题,
    这类错误只有"解析一遍脚本"才能拦住。无 node 环境自动跳过。"""
    import shutil
    import subprocess
    from pathlib import Path

    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not available")
    html = (Path(serve.__file__).parent / "web" / "index.html").read_text(encoding="utf-8")
    # 逐段校验**所有**内联脚本(head 里还有 D3 主题初始化的小脚本); 只查第一段
    # 会让 head 脚本的语法错误溜过——那同样导致整页不工作。
    blocks, rest = [], html
    while "<script>" in rest:
        rest = rest.split("<script>", 1)[1]
        js, rest = rest.split("</script>", 1)
        blocks.append(js)
    assert blocks, "面板没有内联脚本(结构变了?)"
    for i, js in enumerate(blocks):
        out = tmp_path / f"panel{i}.js"
        out.write_text(js, encoding="utf-8")
        r = subprocess.run([node, "--check", str(out)], capture_output=True, text=True)
        assert r.returncode == 0, f"面板内联脚本[{i}]语法错误:\n{r.stderr}"


def _head(url):
    """取 X-Total-Count 响应头(feed 窗口内真实总数, 与 body 截断长度解耦)。"""
    with urllib.request.urlopen(url, timeout=5) as r:
        r.read()
        return r.headers.get("X-Total-Count")


def test_serve_health_stats_and_page(tmp_path):
    srv, base = _serve(tmp_path)
    try:
        st, body = _get_url(f"{base}/healthz")
        assert st == 200 and body["ok"] is True
        st, body = _get_url(f"{base}/api/stats")
        assert st == 200 and body["kpi"]["searches"] == 0
        st, body = _get_url(f"{base}/api/health")
        assert body["exists"] is True
        # 桥就绪标志: 跨环境只断类型(本机可能 True, CI False), 值本身环境相关
        assert isinstance(body["spider_ready"], bool)
        assert body["spider_ready"] == srv.spider.ready()   # ready() 结果缓存一致
        req = urllib.request.Request(f"{base}/")
        with urllib.request.urlopen(req, timeout=5) as r:
            html = r.read().decode()
        assert "Agent-KB 观测面板" in html
    finally:
        srv.shutdown()
        srv.server_close()


def test_serve_since_until_invalid_rejected(tmp_path):
    """§58(第四十轮): 非法 since/until 参与字符串比较式过滤会静默滤空,
    面板把"参数写错"显示成"窗口内真没数据"(假空态)。入口 fail-loud 400。"""
    srv, base = _serve(tmp_path)
    try:
        st, body = _get_any(f"{base}/api/stats?since=2026-13-99")
        assert st == 400 and "since" in body["error"]
        st, body = _get_any(f"{base}/api/stats?until=%E5%9E%83%E5%9C%BE")  # 垃圾
        assert st == 400 and "until" in body["error"]
        st, body = _get_url(f"{base}/api/stats?since=2026-10-01")
        assert st == 200  # 合法日期照常
    finally:
        srv.shutdown()
        srv.server_close()


def test_serve_token_enforced(tmp_path):
    srv, base = _serve(tmp_path, token="s3cret")
    try:
        _get_url(f"{base}/healthz")  # healthz 免鉴权
        try:
            _get_url(f"{base}/api/stats")
            raise AssertionError("无 token 应 401")
        except urllib.error.HTTPError as e:
            assert e.code == 401
        st, _ = _get_url(f"{base}/api/stats", token="s3cret")
        assert st == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_serve_session_cookie_replaces_token_in_url(tmp_path):
    """E1(2026-11-02): token 曾常驻每个请求的 URL query(浏览器历史/Referer/分享
    链接全泄明文)。改为 ticket 换 HttpOnly cookie: /api/session?ticket=<token>
    发 Set-Cookie, 之后 /api/* 凭 cookie 过鉴权, query 不再需要 token。"""
    srv, base = _serve(tmp_path, token="s3cret")
    try:
        # 错 ticket 拒绝
        st, _ = _get_any(f"{base}/api/session?ticket=wrong")
        assert st == 403
        # 正确 ticket → Set-Cookie
        with urllib.request.urlopen(f"{base}/api/session?ticket=s3cret", timeout=5) as r:
            assert r.status == 200
            ck = r.headers.get("Set-Cookie", "")
        assert "kb_tk=" in ck and "HttpOnly" in ck
        # cookie 即可过鉴权(URL 无 token)
        req = urllib.request.Request(f"{base}/api/stats")
        req.add_header("Cookie", ck.split(";")[0])
        with urllib.request.urlopen(req, timeout=5) as r:
            assert r.status == 200
    finally:
        srv.shutdown()
        srv.server_close()


def test_serve_trend_export_and_caller_all(tmp_path):
    """B1 趋势 / B4 导出 / caller=all(追因跨项目快照)三个新端点口径。"""
    import datetime as dt
    today = dt.date.today().isoformat()
    yest = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    srv, base = _serve(tmp_path)
    rows = [
        {"kind": "search", "trace_id": "t1", "ts": f"{yest}T10:00:00+08:00",
         "source": "cli", "caller_repo": "p1", "query": "缺口词", "returned": [],
         "duration_ms": 30,
         "layers": [{"repo": "docs", "scanned": 5, "matched": []}]},
        {"kind": "search", "trace_id": "t2", "ts": f"{today}T10:00:00+08:00",
         "source": "cli", "caller_repo": "p2", "query": "vite", "returned": ["k1"],
         "duration_ms": 90,
         "layers": [{"repo": "docs", "scanned": 5, "matched": [{"id": "k1", "title": "T"}]}]},
    ]
    lines = [json.dumps({"kind": "meta", "schema": serve.kbtrace.SCHEMA})] + \
        [json.dumps(r, ensure_ascii=False) for r in rows]
    (tmp_path / "traces" / "ledger.jsonl").write_text("\n".join(lines) + "\n",
                                                      encoding="utf-8")
    try:
        st, body = _get_url(f"{base}/api/trend")
        assert st == 200 and len(body["days"]) == 2
        d0 = {x["day"]: x for x in body["days"]}
        assert d0[yest]["searches"] == 1 and d0[yest]["hits"] == 0
        assert d0[today]["median_ms"] == 90
        # 趋势与 stats 同 caller 过滤
        st, body = _get_url(f"{base}/api/trend?caller=p1")
        assert [x["day"] for x in body["days"]] == [yest]
        # 导出: 与面板榜单同一实现出口; 未知 kind 是客户端错误 400 不是 500
        st, body = _get_url(f"{base}/api/export?kind=zero")
        assert st == 200 and body[0]["query"] == "缺口词"
        st, body = _get_url(f"{base}/api/export?kind=dead")
        assert st == 200 and body == []      # k1 只返回 1 次, 未过 min_returned
        st, body = _get_any(f"{base}/api/export?kind=bogus")
        assert st == 400
        # caller=all: 单项目视图追因要"跨全部 caller 但仍是列表口径"——
        # feed 必须回两个项目的行(否则别的项目的零命中永远追不到)
        st, body = _get_url(f"{base}/api/feed?caller=all")
        assert [x["trace_id"] for x in body] == ["t2", "t1"]
        st, body = _get_url(f"{base}/api/feed?caller=p1")
        assert [x["trace_id"] for x in body] == ["t1"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_synthetic_callers_rules():
    """P0-1 判据: pytest tmp_path 形态 caller 直接剔; 其余按"该 caller 全部 search
    的最大 scanned ≤ 2"剔(合成夹具只有 1-2 条条目)。

    关键防误伤: 真实仓只要**出现过一次**大扫描就不再是合成——用"全部"而非"存在",
    否则刚接入(库里还只有 1-2 条)的真实仓会被永久误剔。
    """
    real = _search("r1", "flysee_video_web", "vite", ["k1"])          # scanned=5
    tiny = _search("t1", "proj", "vite", ["kb-1"])
    tiny["layers"] = [{"repo": "proj", "scanned": 1, "matched": []}]
    grew = [_search("g1", "newrepo", "a", [], ), _search("g2", "newrepo", "b", ["k"])]
    grew[0]["layers"] = [{"repo": "newrepo", "scanned": 1, "matched": []}]
    pytest_like = _search("p1", "test_cli_index_then_search_jso0", "vite", ["kb-1"])
    pytest_like["layers"] = []            # scanned 缺失也照剔(靠 caller 名铁证)
    S = [real, tiny, *grew, pytest_like]
    assert stats.synthetic_callers(S) == {"proj", "test_cli_index_then_search_jso0"}
    assert "newrepo" not in stats.synthetic_callers(S)   # 长过 → 不是合成
    assert "flysee_video_web" not in stats.synthetic_callers(S)


def test_denoise_drops_both_kinds_and_counts():
    """get 与 search 同批剔: 只剔 search 会让消费率分母被剔而分子不剔。"""
    tiny = _search("t1", "proj", "vite", ["kb-1"])
    tiny["layers"] = [{"repo": "proj", "scanned": 1, "matched": []}]
    S = [_search("r1", "real", "vite", ["k1"]), tiny]
    G = [_get("r1", "k1", "real"), _get("t1", "kb-1", "proj")]
    s, g, n, bad = stats.denoise(S, G)
    assert [x["trace_id"] for x in s] == ["r1"]
    assert [x["trace_id"] for x in g] == ["r1"]
    assert n == 2 and bad == {"proj"}
    assert stats.denoise(S, G)[2:] == stats.denoise(S, G)[2:]   # 幂等(纯函数)
    clean = [_search("r1", "real", "vite", ["k1"])]
    assert stats.denoise(clean, []) == (clean, [], 0, set())


def test_serve_stats_reports_dropped_synthetic(tmp_path):
    """剔噪必须可见: 面板要拿到被剔条数与 caller 名单; `?raw=1` 回原始口径。"""
    import datetime as _dt
    today = _dt.date.today().isoformat()
    srv, base = _serve(tmp_path)      # _serve 负责建 traces/, 账本随后写入
    rows = [{"kind": "search", "trace_id": "real1", "source": "cli",
             "caller_repo": "real", "query": "连接池 耗尽", "returned": [],
             "ts": f"{today}T10:00:00+08:00",
             "layers": [{"repo": "real", "scanned": 195, "matched": []}]}]
    # 三条合成 search(同一合成 caller): 复刻"零消费榜被合成夹具刷屏"的真实形态
    for i in (1, 2, 3):
        rows.append({"kind": "search", "trace_id": f"syn{i}", "source": "cli",
                     "caller_repo": "proj", "query": "vite",
                     "ts": f"{today}T11:0{i}:00+08:00",
                     "returned": ["kb-20261012-aaaa"],
                     "layers": [{"repo": "proj", "scanned": 1,
                                 "matched": [{"id": "kb-20261012-aaaa",
                                              "title": "Vite"}]}]})
    # 窗口外的一条合成事件: synthetic_count 必须与卡面窗口口径对账(走查实测
    # 标注 157 vs 两态 KPI 差 70 的根因就是全账本数冒充窗口数)
    rows.append({"kind": "search", "trace_id": "synold", "source": "cli",
                 "caller_repo": "proj", "query": "vite", "returned": [],
                 "ts": "2026-10-01T11:00:00+08:00",
                 "layers": [{"repo": "proj", "scanned": 1, "matched": []}]})
    lines = [json.dumps({"kind": "meta", "schema": serve.kbtrace.SCHEMA})] + \
        [json.dumps(r, ensure_ascii=False) for r in rows]
    (tmp_path / "traces" / "ledger.jsonl").write_text("\n".join(lines) + "\n",
                                                      encoding="utf-8")
    try:
        st, d = _get_url(f"{base}/api/stats")
        assert st == 200
        assert d["synthetic_count"] == 4 and d["synthetic_callers"] == ["proj"]
        assert d["kpi"]["searches"] == 1
        # 窗口口径对账: 剔噪数只算窗口内的(10-01 那条合成事件在窗口外)
        st, dw = _get_url(f"{base}/api/stats?since={today}")
        assert dw["kpi"]["searches"] == 1
        assert dw["synthetic_count"] == 3
        assert dw["synthetic_total"] == 4
        # 单日聚焦(回归实测 -812 的根因: 减数没同步过窗口, 窄窗口减穿成负数)
        st, dd = _get_url(f"{base}/api/stats?since={today}&until={today}")
        assert dd["synthetic_count"] == 3
        st, dz = _get_url(f"{base}/api/stats?since=2020-01-01&until=2020-01-02")
        assert dz["synthetic_count"] == 0 and dz["kpi"]["searches"] == 0
        # 合成条目不得进榜(实测: 两条合成夹具各 61 次并列零消费榜首)
        assert [x["id"] for x in d["dead_weight"]] == []
        # 矩阵同理: 合成 caller 不是"项目", 不配占一行
        st, rows2 = _get_url(f"{base}/api/callers")
        assert [x["caller"] for x in rows2] == ["real"]
        # raw=1 原始口径: 合成事件回来了, 且不再报"已剔除"
        st, d2 = _get_url(f"{base}/api/stats?raw=1")
        assert d2["kpi"]["searches"] == 5 and d2["synthetic_count"] == 0
        assert d2["dead_weight"][0]["id"] == "kb-20261012-aaaa"
        assert d2["dead_weight"][0]["returned"] == 3
        # Q4: 审计明细两口径都给(raw 态正是拿来自查误伤的, 留空=逃生门失效),
        # 且必须带 max_scanned —— 判断 tiny-scan 有没有冤枉真实小库全靠它。
        assert [x["caller"] for x in d2["synthetic_detail"]] == ["proj"]
        assert d2["synthetic_detail"][0]["events"] == 4
        assert d2["synthetic_detail"][0]["why"] == "tiny-scan"
        assert d2["synthetic_detail"][0]["max_scanned"] == 1
        assert d["synthetic_detail"] == d2["synthetic_detail"]
        st, rows3 = _get_url(f"{base}/api/feed?raw=1")
        assert {x["trace_id"] for x in rows3} == {
            "real1", "syn1", "syn2", "syn3", "synold"}
        st, rows4 = _get_url(f"{base}/api/feed")
        assert [x["trace_id"] for x in rows4] == ["real1"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_serve_quality_federation(tmp_path):
    """A5: /api/quality 聚合 = 本 serve root + 显式 --repos 的库, 二者分列;
    traces 里出现但未配置的 caller 进 uncovered(不猜路径、不拿本库数字冒充)。"""
    def _idx(root: Path, n: int, status="accepted"):
        (root / "kb").mkdir(parents=True, exist_ok=True)
        (root / "kb" / "index.jsonl").write_text("\n".join(
            json.dumps({"id": f"kb-20261101-{i:04d}", "title": f"t{i}",
                        "status": status, "confidence": "verified", "type": "pitfall",
                        "domain": "backend", "scope": "project", "path": "kb/x.md",
                        "tags": ["a"]}) for i in range(n)), encoding="utf-8")

    _idx(tmp_path, 2)
    extra = tmp_path / "biz" / "docs"
    _idx(extra, 3, status="draft")
    # caller "p9" 在 traces 里出现过但没配 --repos → uncovered
    (tmp_path / "traces").mkdir()
    (tmp_path / "traces" / "ledger.jsonl").write_text(
        json.dumps({"kind": "meta", "schema": serve.kbtrace.SCHEMA}) + "\n" +
        json.dumps({"kind": "search", "trace_id": "t1",
                    "ts": dt.datetime.now().isoformat(), "source": "cli",
                    "caller_repo": "p9", "query": "vite", "returned": ["k1"],
                    "layers": [{"repo": "docs", "scanned": 5,
                                "matched": [{"id": "k1", "title": "T"}]}]}) + "\n",
        encoding="utf-8")
    srv = serve.ServeServer(("127.0.0.1", 0), tmp_path, None, None, quiet=True,
                            extra_repos={"biz": extra})
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        st, d = _get_url(f"{base}/api/quality")
        assert st == 200
        assert d["total"] == 5                     # 合计(联邦)
        assert {r["repo"]: r["total"] for r in d["repos"]} == {d["repo"]: 2, "biz": 3}
        assert d["draft_backlog"] == 3
        assert "p9" in d["uncovered"]
        assert d["errors"] == {}
        # 坏路径: 不进 repos, 但要如实报错而不是整体 500
        srv.extra_repos["ghost"] = tmp_path / "nowhere"
        st, d = _get_url(f"{base}/api/quality")
        assert "ghost" in d["errors"] and d["total"] == 5
    finally:
        srv.shutdown()


def test_serve_quality_entries_drill_down(tmp_path):
    """B3 数字下钻: 卡上五计数与 /api/quality/entries 清单必须同源同数(旧实现各自
    sum(), 清单从未存在, 数字点不开)。参数错必须 400 —— 空清单会被读成"这个分类
    真的没有条目"(假空, §58 同族)。"""
    def _idx(root: Path, recs):
        (root / "kb").mkdir(parents=True, exist_ok=True)
        (root / "kb" / "index.jsonl").write_text("\n".join(
            json.dumps(r, ensure_ascii=False) for r in recs), encoding="utf-8")

    def _rec(i, **over):
        r = {"id": f"kb-20261101-{i:04d}", "title": f"标题{i}", "type": "pitfall",
             "domain": ["backend"], "tags": ["a"], "scope": "project",
             "status": "accepted", "confidence": "verified",
             "path": f"kb/pitfall/backend/{i}.md", "updated": "2026-10-01"}
        r.update(over)
        return r

    recs = [_rec(1, status="draft", tags=[]),                       # draft + no_tags
            _rec(2, confidence="speculative"),
            _rec(3, tags=["needs-scope-review"]),
            _rec(4)]
    _idx(tmp_path, recs)
    extra = tmp_path / "biz" / "docs"
    _idx(extra, [_rec(5, status="draft"), _rec(6, status="draft")])
    srv, base = _serve(tmp_path)
    srv.extra_repos = {"biz": extra}
    # Q11 使用度账本: kb-...-0005 被两条 search 返回(scanned=9 防误判合成), 其中
    # t1 有同 trace 的 ok get → 计 1 次消费读。caller "app" 非合成形态。
    today = dt.date.today().isoformat()

    def _sv(tid, ret):
        return {"kind": "search", "trace_id": tid, "source": "cli",
                "caller_repo": "app", "query": "vite", "returned": ret,
                "ts": f"{today}T10:00:00+08:00",
                "layers": [{"repo": "app", "scanned": 9,
                            "matched": [{"id": i, "title": "T"} for i in ret]}]}
    led = [json.dumps({"kind": "meta", "schema": serve.kbtrace.SCHEMA}),
           json.dumps(_sv("t1", ["kb-20261101-0005", "kb-20261101-0001"])),
           json.dumps(_sv("t2", ["kb-20261101-0005"])),
           json.dumps({"kind": "get", "trace_id": "t1", "source": "cli",
                       "caller_repo": "app", "id": "kb-20261101-0005",
                       "layer": "biz", "ok": True, "chars": 900,
                       "ts": f"{today}T10:00:05+08:00"})]
    (tmp_path / "traces" / "ledger.jsonl").write_text("\n".join(led) + "\n",
                                                      encoding="utf-8")
    try:
        st, q = _get_url(f"{base}/api/quality")
        assert q["draft_backlog"] == 3            # 联邦合计(本库 1 + biz 2)
        # 单库口径: 数字 == 清单条数, 且行字段够面板辨认
        st, d = _get_url(f"{base}/api/quality/entries?kind=draft")
        assert st == 200 and d["total"] == 1 and len(d["rows"]) == 1
        assert d["rows"][0]["id"] == "kb-20261101-0001"
        assert d["rows"][0]["path"].startswith("kb/")
        # 联邦合计口径: repo=all 跨库拼, 才与卡上 3 对得上
        st, d = _get_url(f"{base}/api/quality/entries?kind=draft&repo=all")
        assert d["total"] == 3 == q["draft_backlog"]
        assert {r["repo"] for r in d["rows"]} == {q["repo"], "biz"}
        # 其余分类同理同源
        for kind, n in (("speculative", 1), ("needs_scope", 1), ("no_tags", 1)):
            st, d = _get_url(f"{base}/api/quality/entries?kind={kind}")
            assert st == 200 and d["total"] == n, kind
        # 清单不截断(曾定 200 上限, 制造过"卡上 228 / 清单 200"的新对不上):
        # 任何分类 rows 长度恒等于 total。
        st, d = _get_url(f"{base}/api/quality/entries?kind=draft&repo=all")
        assert len(d["rows"]) == d["total"] and "cap" not in d
        # Q11: 每行带使用度(hits/reads/last_used), 且按 hits 倒序。账本里 kb-...-0005
        # 被返回两次并读全文一次, 应排在最前。
        assert all({"hits", "reads", "last_used"} <= set(r) for r in d["rows"])
        assert d["rows"][0]["id"] == "kb-20261101-0005"
        assert d["rows"][0]["hits"] == 2 and d["rows"][0]["reads"] == 1
        assert d["rows"][-1]["hits"] == 0   # 从未被检索的 draft 沉底
        # 显式指名 biz 库
        st, d = _get_url(f"{base}/api/quality/entries?kind=draft&repo=biz")
        assert d["total"] == 2 and {r["id"] for r in d["rows"]} == {
            "kb-20261101-0005", "kb-20261101-0006"}
        # fail-loud: 未知 kind / 未知 repo 都是 400, 不回空清单
        st, d = _get_any(f"{base}/api/quality/entries?kind=bogus")
        assert st == 400 and "kind" in d["error"]
        st, d = _get_any(f"{base}/api/quality/entries?kind=draft&repo=ghost")
        assert st == 400 and "repo" in d["error"]
        st, d = _get_any(f"{base}/api/quality/entries")
        assert st == 400                                   # 缺 kind
    finally:
        srv.shutdown()


def test_serve_entry_source_readonly_lookup(tmp_path):
    """Q8: 清单点"原文"→ /api/entry。路径只经索引 id 反查(不接受任意 path 参数),
    查无此条 404、缺 id/未知库 400 —— 三者必须分开, 混成一个码就没法判断是拼错了
    还是条目真没了。配名(biz)与目录标签(面板"库"列显示的那个)都须能解析。"""
    def _idx(root: Path, recs, bodies):
        (root / "kb" / "pitfall" / "backend").mkdir(parents=True, exist_ok=True)
        (root / "kb" / "index.jsonl").write_text("\n".join(
            json.dumps(r, ensure_ascii=False) for r in recs), encoding="utf-8")
        for rel, txt in bodies.items():
            (root / rel).write_text(txt, encoding="utf-8")

    def _rec(i, root_name):
        return {"id": f"kb-20261102-{i:04d}", "title": f"标题{i}", "type": "pitfall",
                "domain": ["backend"], "tags": ["a"], "scope": "project",
                "status": "draft", "confidence": "speculative",
                "path": f"kb/pitfall/backend/{i}.md", "updated": "2026-11-02",
                "repo": root_name}

    _idx(tmp_path, [_rec(1, "self")],
         {"kb/pitfall/backend/1.md": "# 标题1\n\n正文本库\n"})
    extra = tmp_path / "somewhere" / "docs"
    _idx(extra, [_rec(2, "biz")], {"kb/pitfall/backend/2.md": "# 标题2\n\n正文他库\n"})
    srv, base = _serve(tmp_path)
    srv.extra_repos = {"biz": extra}
    try:
        st, d = _get_url(f"{base}/api/entry?id=kb-20261102-0001")
        assert st == 200 and "正文本库" in d["markdown"]
        # 声明名与目录标签(somewhere)两种写法都要能命中同一库
        for alias in ("biz", "somewhere"):
            st, d = _get_url(f"{base}/api/entry?id=kb-20261102-0002&repo={alias}")
            assert st == 200 and "正文他库" in d["markdown"], alias
        st, d = _get_any(f"{base}/api/entry?id=kb-20261102-9999")
        assert st == 404                                   # 查无此条
        st, d = _get_any(f"{base}/api/entry")
        assert st == 400 and "id" in d["error"]
        st, d = _get_any(f"{base}/api/entry?id=kb-20261102-0002&repo=ghost")
        assert st == 400 and "repo" in d["error"]
        # R8: 不带 repo = 跨库找(原文里 related 的 kb-id 大概率不在当前库)。
        # 本库优先, 找不到再按 --repos 声明序。
        st, d = _get_url(f"{base}/api/entry?id=kb-20261102-0002")
        assert st == 200 and "正文他库" in d["markdown"] and d["repo"]
        st, d = _get_any(f"{base}/api/entry?id=kb-20261102-8888")
        assert st == 404
    finally:
        srv.shutdown()


def test_trend_daily_p95(tmp_path):
    """R7: 趋势逐日补 p95_ms, 分位序位与 KPI latency 的 pctl 一致(ceil(95/100*n)-1)。
    此前只有中位数——"某天毛刺"恰恰是 P95 恶化而中位数不动的形态, 会被抹平。"""
    today = dt.date.today().isoformat()
    durs = [10, 20, 30, 40, 200]     # n=5 → p95 序位 ceil(0.95*5)-1=4 → 200
    rows = [json.dumps({"kind": "meta", "schema": serve.kbtrace.SCHEMA})]
    for i, dm in enumerate(durs):
        rows.append(json.dumps({
            "kind": "search", "trace_id": f"t{i}", "source": "cli",
            "caller_repo": "app", "query": "q", "returned": [],
            "duration_ms": dm, "ts": f"{today}T09:0{i}:00+08:00",
            "layers": [{"repo": "app", "scanned": 9, "matched": []}]}))
    srv, base = _serve(tmp_path)     # _serve 建 traces/; 账本随后写入
    (tmp_path / "traces" / "ledger.jsonl").write_text(
        "\n".join(rows) + "\n", encoding="utf-8")
    try:
        st, d = _get_url(f"{base}/api/trend")
        assert st == 200
        day = [x for x in d["days"] if x["day"] == today][0]
        assert day["p95_ms"] == 200 and day["median_ms"] == 30
        # 与 KPI latency 同分位同值(KPI 是整窗口口径, 这里只有一天)
        st, s = _get_url(f"{base}/api/stats")
        assert s["latency"]["p95_ms"] == day["p95_ms"]
    finally:
        srv.shutdown()


def test_export_quality_rejects_window_params(tmp_path):
    """Q3: kind=quality 是索引口径, 与 caller/窗口无关。此前统一拼参把它一起带上,
    参数被静默丢弃 —— 导出方以为按窗口筛了(§58 假数据同族)。现在显式 400。"""
    srv, base = _serve(tmp_path)
    (tmp_path / "kb").mkdir(exist_ok=True)
    (tmp_path / "kb" / "index.jsonl").write_text(json.dumps(
        {"id": "kb-20261102-0001", "title": "t", "status": "accepted",
         "confidence": "verified", "type": "pitfall", "domain": "backend",
         "scope": "project", "path": "kb/x.md", "tags": ["a"]}), encoding="utf-8")
    try:
        st, d = _get_url(f"{base}/api/export?kind=quality")
        assert st == 200                                    # 裸请求正常
        st, d = _get_any(f"{base}/api/export?kind=quality&since=2026-10-01")
        assert st == 400 and "quality" in d["error"]
        st, d = _get_any(f"{base}/api/export?kind=quality&caller=x")
        assert st == 400
        # 窗口类 kind 不受影响
        st, d = _get_url(f"{base}/api/export?kind=zero&since=2026-10-01")
        assert st == 200
    finally:
        srv.shutdown()


def test_parse_repos_requires_name_eq_path():
    assert serve.parse_repos(["Biz=..\\x\\docs"]) == {"biz": Path("..\\x\\docs")}
    assert serve.parse_repos(None) == {}
    for bad in ("justname", "=x", "n="):
        try:
            serve.parse_repos([bad])
        except ValueError:
            continue
        raise AssertionError(f"应拒绝 {bad!r}")


def test_bind_without_token_refused():
    try:
        serve.resolve_bind("0.0.0.0", None)
        raise AssertionError("非本机绑定无 token 必须拒绝")
    except ValueError:
        pass
    assert serve.resolve_bind("0.0.0.0", "tok") == "0.0.0.0"
    assert serve.resolve_bind("127.0.0.1", None) == "127.0.0.1"


def test_serve_survives_dirty_events(tmp_path):
    """§26 回归: 脏事件(null returned / 非列表 / 非数值 chars / 非对象行)不得让
    API 连接裸断(旧行为: TypeError 穿透 → 客户端"无法连接")。"""
    import datetime as _dt
    srv, base = _serve(tmp_path)
    try:
        f = tmp_path / "traces" / f"{_dt.date.today():%Y-%m-%d}.jsonl"
        rows = [{"kind": "meta", "schema": serve.kbtrace.SCHEMA},
                {"kind": "search", "trace_id": "t1", "ts": "2026-10-21T10:00:00+08:00",
                 "caller_repo": "x", "query": "q", "returned": None, "filters": {}},
                {"kind": "search", "trace_id": "t2", "ts": "2026-10-21T10:01:00+08:00",
                 "caller_repo": "x", "query": "q", "returned": "abc", "filters": {}},
                {"kind": "get", "trace_id": "t1", "id": "kb-1", "ok": True, "chars": "abc"},
                [1, 2, 3]]
        f.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows),
                     encoding="utf-8")
        for ep in ("stats?w=0", "feed?limit=10", "callers"):
            st, _ = _get_url(f"{base}/api/{ep}")
            assert st == 200, ep
    finally:
        srv.shutdown()
        srv.server_close()


def test_panel_api_requests_use_apiurl():
    """token 态回归守护(E1 改版): 面板所有 /api/* 请求(fetch 与 EventSource)必须经
    apiUrl() 统一出口, 禁止手拼——实测踩坑: stats/feed/health 曾漏带导致 token 态
    静默 401 全空。E1 后 apiUrl 不再注 token(凭 cookie), 唯一允许把凭据写进 URL 的
    是 /api/session 的 ticket 交换(一次性, 换完即洗 URL)。"""
    import re
    from pathlib import Path
    from kb.serve import _asset_dir
    html = (Path(_asset_dir()) / "index.html").read_text(encoding="utf-8")
    bad = [m.group(0)[:70] for m in
           re.finditer(r"(?:fetch|EventSource)\(\s*(`[^`]*`|'[^']*')", html)
           if "/api/" in m.group(0) and "/api/session" not in m.group(0)]
    assert not bad, f"面板 /api/* 请求未经 apiUrl() 手拼 URL(须走 apiUrl 统一出口): {bad}"
    assert "function apiUrl(" in html, "apiUrl() 统一出口必须存在"
    # E1 反向守护: token 只许出现在 session 交换处; 常规请求再拼 token = 回退旧泄露面
    leak = [m.group(0)[:60] for m in
            re.finditer(r"(?:fetch|EventSource)\([^)]{0,120}token", html)]
    assert all("/api/session" in m for m in leak), f"token 混入常规请求 URL: {leak}"


def test_panel_custom_clickables_are_keyboard_reachable():
    """§59(D-50) a11y 回归守护: 自定义(非 button/a)元素绑 onclick 必须同时具备
    tabindex + role + 键盘处理——实测踩坑: 联邦矩阵下钻行只有 onclick, 是全屏唯一
    "仅鼠标可操作"的交互, 键盘 Tab 直接跳过(同页零命中榜行/检索流条目都做对了)。"""
    import re
    from pathlib import Path
    from kb.serve import _asset_dir
    html = (Path(_asset_dir()) / "index.html").read_text(encoding="utf-8")
    # 自定义可点模板(div/tr 生成 HTML 时)须带 tabindex+role=button+aria-label
    for cls in ("matrix-link", "bar"):
        tpl = [m.group(0) for m in re.finditer(rf'<(?:tr|div) class="[^"]*{cls}[^"]*"[^>]*>',
                                               html)]
        for t in tpl:
            if 'data-zq' in t or 'matrix-link' in t:  # 可下钻的行才要求键盘可达
                assert 'tabindex=' in t, f"可点击行缺 tabindex(键盘不可达): {t[:80]}"
    # 矩阵行绑定处须有 Enter/空格键盘处理
    i = html.find("querySelectorAll('.matrix-link')")
    assert i >= 0, "矩阵下钻绑定缺失"
    assert "onkeydown" in html[i:i + 500], "矩阵下钻行缺键盘处理(Enter/空格)"


# ---- B-2: /api/replay 与 /api/spider(懒启动桥) ----------------------------

def _seed_trace(tmp_path, search_ev, get_evs):
    from kb import trace as kbtrace
    for ev in [search_ev] + get_evs:
        kbtrace.append_event(ev, tmp_path)


def test_api_replay_returns_record_scoped_to_trace(tmp_path):
    srv, base = _serve(tmp_path)
    ev = _search("rb-1", "a", "vite", ["k1", "k2"])
    ev["layers"][0]["matched"] = [
        {"id": "k1", "title": "T1", "hit_fields": ["title"], "hit_spans": [[0, 2]]},
        {"id": "k2", "title": "T2", "hit_fields": ["tag"], "hit_spans": []}]
    # 同 trace 的 get → you; 其他 trace 的 get(k1) 不得混入
    _seed_trace(tmp_path, ev, [_get("rb-1", "k1", "a"), _get("other", "k2", "a")])
    try:
        st, rec = _get_url(f"{base}/api/replay/rb-1")
        assert st == 200 and rec["format"] == "prompt-spider-session/v1"
        assert rec["id"] == "rb-1"
        by_id = {e["id"]: e for e in rec["events"]}
        assert by_id["k1"]["route"] == "you"      # 本 trace 已读
        assert by_id["k2"]["route"] == "code"     # 其他 trace 的 get 不算已读
        st, body = _get_any(f"{base}/api/replay/missing")
        assert st == 404 and "not found" in body["error"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_spider_uses_bridge_and_caches(tmp_path, monkeypatch):
    srv, base = _serve(tmp_path)
    calls = []

    class FakeMcp:
        def tool(self, name, args):
            calls.append((name, args))
            if name == "spider_import_session":
                return {"id": f"sid{len(calls)}",
                        "previewUrl": "http://127.0.0.1:9/?session=x#token=t"}
            return {}

    srv.spider._mcp = FakeMcp()  # 注入假桥, 不真 spawn node
    ev = _search("rb-2", "a", "vite", ["k1"])
    ev["layers"][0]["matched"] = [{"id": "k1", "title": "T1", "hit_fields": ["title"]}]
    _seed_trace(tmp_path, ev, [])
    try:
        st, body = _get_url(f"{base}/api/spider/rb-2")
        assert st == 200 and body["previewUrl"].startswith("http://127.0.0.1:9/")
        # 整页回放: previewUrl 原样透传(不注 chrome=none、不动 #token), 面板直接新标签打开
        assert "chrome=none" not in body["previewUrl"]
        assert body["previewUrl"].endswith("#token=t")
        st2, body2 = _get_url(f"{base}/api/spider/rb-2")   # 缓存命中: 不再 import
        assert body2 == body
        assert sum(1 for n, _ in calls if n == "spider_import_session") == 1
        # 导入后默认"自动重播+循环"(用户诉求): restart+loop 必须下发
        ctrl = [a for n, a in calls if n == "spider_control_playback"]
        assert ctrl and ctrl[0]["command"] == {"loop": True, "action": "restart"}
        st, _ = _get_any(f"{base}/api/spider/nope")
        assert st == 404
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_spider_dependency_missing_is_503_hint(tmp_path, monkeypatch):
    from kb import spider_live
    srv, base = _serve(tmp_path)
    ev = _search("rb-3", "a", "vite", ["k1"])
    _seed_trace(tmp_path, ev, [])
    # 确定性模拟缺依赖(本机等开发机可能真装了 Node+克隆, 不能依赖环境)
    monkeypatch.setattr(spider_live, "find_spider_home",
                        lambda explicit=None: (_ for _ in ()).throw(
                            FileNotFoundError("找不到 prompt-spider-ui 克隆")))
    try:
        st, body = _get_any(f"{base}/api/spider/rb-3")   # 缺克隆 → 503 + 指引
        assert st == 503 and "克隆" in body["error"]
        # 记住失败不再重试(第二次同样 503 且不卡)
        st2, _ = _get_any(f"{base}/api/spider/rb-3")
        assert st2 == 503
    finally:
        srv.shutdown()
        srv.server_close()


def test_api_spider_revives_after_bridge_process_death(tmp_path, monkeypatch):
    """桥进程运行中途死亡(被杀/崩溃→管道写入 [Errno 22])后, 后续请求必须自动重生桥,
    而不是被 _dead 永久短路。实测踩坑(第九轮走查): 一次桥死亡让 serve 余生回放全降级。"""
    from kb import spider_live

    class DeadMcp:                       # 已 spawn 但进程已死(p.poll() 非 None)
        class p:
            @staticmethod
            def poll():
                return 1
        def close(self):
            pass

    srv, base = _serve(tmp_path)
    ev = _search("rb-4", "a", "vite", ["k1"])
    ev["layers"][0]["matched"] = [{"id": "k1", "title": "T1", "hit_fields": ["title"]}]
    _seed_trace(tmp_path, ev, [])
    srv.spider._mcp = DeadMcp()          # 模拟: 之前成功起过桥, 现在进程死了
    respawn = {"n": 0}

    class RevivedMcp:
        p = None                          # 假桥无真进程(_alive 视为存活)

        def tool(self, name, args):
            if name == "spider_import_session":
                respawn["n"] += 1
                return {"id": "sid-new", "previewUrl": "http://127.0.0.1:9/?session=new"}
            return {}

    monkeypatch.setattr(spider_live, "SpiderMcp", lambda home: RevivedMcp())
    monkeypatch.setattr(spider_live, "find_spider_home", lambda explicit=None: tmp_path)
    try:
        st, body = _get_url(f"{base}/api/spider/rb-4")
        assert st == 200 and body["previewUrl"].endswith("session=new")
        assert respawn["n"] == 1          # 死桥被替换重spawn, 而非 _dead 短路 503
        # 死亡前缓存的旧 URL 指向已死进程, 必须作废重导而非原样返回
        srv.spider._mcp = DeadMcp()
        st2, body2 = _get_url(f"{base}/api/spider/rb-4")
        assert st2 == 200 and respawn["n"] == 2
    finally:
        srv.shutdown()
        srv.server_close()


# ---- /api/ingest(FR-2.5 团队态直播通道) ---------------------------------

def _post_json(url, obj, token=None):
    data = json.dumps(obj).encode()
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/json"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode())


def test_ingest_401_drains_body_so_response_survives(tmp_path):
    """§76 实锤: 旧 do_POST 在鉴权失败回 401 时不回读请求体就 close——
    http.client 分"头段+体段"两次 write, 体段晚于 close 到达即触发服务端
    RST(Windows), 把已写出的 401 吞成 ConnectionReset/Aborted(全量套件
    test_ingest 偶发 flaky 的根因, 探针受控时序复现)。修复后: 出错路径先
    drain body, 慢体客户端也能稳定读到 401。"""
    srv, base = _serve(tmp_path, token="tk")
    try:
        port = int(base.rsplit(":", 1)[1])
        body = json.dumps(_search("slow-1", "p", "q", [])).encode()
        head = (f"POST /api/ingest HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n")
        s = socket.create_connection(("127.0.0.1", port), timeout=5)
        try:
            s.sendall(head.encode())        # 只发头(无 Authorization → 401)
            time.sleep(0.3)                 # 让服务端先写完 401 并进入收尾
            try:
                s.sendall(body)             # 迟到的 body: 修复前在这里引爆 RST
            except OSError:
                pass                        # 个别平台发送即知关闭, 不影响断言
            data = b""
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                chunk = s.recv(4096)
                if not chunk:
                    break
                data += chunk
            assert data.startswith(b"HTTP/1.0 401"), data[:60]  # 401 必须可读
        finally:
            s.close()
    finally:
        srv.shutdown()
        srv.server_close()


def test_ingest_append_dedup_and_redlines(tmp_path):
    srv, base = _serve(tmp_path, token="tk")
    ev = _search("ing-1", "proj-x", "vite", ["k1"], rc=100)
    try:
        st, body = _post_json(f"{base}/api/ingest", ev, token="tk")
        assert st == 200 and body["ok"] and body["deduped"] is False
        st, body = _post_json(f"{base}/api/ingest", ev, token="tk")  # 幂等
        assert body["deduped"] is True
        # 正文键名红线: content 键直接 400
        bad = dict(ev, content="秘密正文")
        st, _ = _post_json(f"{base}/api/ingest", bad, token="tk")
        assert st == 400
        # kind 白名单
        st, _ = _post_json(f"{base}/api/ingest", {"kind": "other"}, token="tk")
        assert st == 400
        # 无 token → 401
        st, _ = _post_json(f"{base}/api/ingest", _search("ing-2", "p", "q", []))
        assert st == 401
        # 落盘可聚合: ingest 的事件进了 traces 事实源
        st, body = _get_url(f"{base}/api/stats?caller=*", token="tk")
        assert body["kpi"]["searches"] >= 1
    finally:
        srv.shutdown()
        srv.server_close()


def test_ingest_rejects_non_string_identity_fields(tmp_path):
    """§52 实锤: 旧 ingest 口不校验身份字段类型——trace_id=list 让幂等 key 元组
    构造处 TypeError(handler 线程崩→连接重置, §26 同构但在写侧);
    caller_repo=dict 虽 200 入账本, 读侧 by_caller 聚合再炸 500。修复后 400 拒收。"""
    srv, base = _serve(tmp_path, token="tk")
    try:
        for k, bad_val in [("trace_id", ["a", "b"]), ("caller_repo", {"evil": 1}),
                           ("ts", {"h": 1}), ("id", [1])]:
            ev = _search("typed-1", "proj-t", "q", [])
            ev[k] = bad_val
            st, body = _post_json(f"{base}/api/ingest", ev, token="tk")
            assert st == 400 and k in body["error"], (k, st, body)
        # 正常事件不受牵连
        st, body = _post_json(f"{base}/api/ingest", _search("typed-ok", "p", "q", []),
                              token="tk")
        assert st == 200 and body["ok"]
    finally:
        srv.shutdown()
        srv.server_close()


def test_read_coerces_non_string_identity_fields(tmp_path):
    """存量脏文件(ingest 修复前入账本/手工写入)读侧同批净化: caller_repo=dict
    降级为'项目未知'并 warn, 聚合/矩阵/实时流不再 500。"""
    import datetime as dt

    from kb import trace as kbtrace
    good = {"kind": "search", "trace_id": "g1", "caller_repo": "good",
            "query": "q", "returned": [], "ts": "2026-10-15T10:00:00+08:00"}
    bad = {"kind": "search", "trace_id": {"weird": 1},
           "caller_repo": {"evil": "dict"}, "query": "q", "returned": [],
           "ts": "2026-10-15T10:00:01+08:00"}
    d = tmp_path / "traces"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{dt.date.today():%Y-%m-%d}.jsonl").write_text(
        "\n".join(json.dumps(x) for x in
                  [{"kind": "meta", "schema": 2}, good, bad]) + "\n",
        encoding="utf-8")
    s, g, warns = kbtrace.read_traces(root=tmp_path)
    assert any("caller_repo 非字符串" in w for w in warns)
    agg = stats.aggregate(s, g)
    assert set(agg["by_caller"]) <= {"?", "good"}    # dict 键不再入 by_caller
    stats.callers(s)
    stats.feed_events(s, g)


def test_ingest_body_key_redline_checks_keys_not_values(tmp_path):
    """红线是"拒收正文**键名**"(PRD 原话)。早期实现把整坨事件序列化后扫
    "content"/"text"/"body" 子串, 值也扫 → query="content" 这类合法检索词被误判 400,
    叠加客户端 _post_ingest 静默吞异常, 团队账本永久缺该事件且无告警(第十轮走查实测)。"""
    srv, base = _serve(tmp_path, token="tk")
    try:
        # 值恰为红线词: 合法检索, 必须放行
        for i, q in enumerate(["content", "text", "body", "正文 content 规范"]):
            ev = _search(f"val-{i}", "proj-v", q, [])
            st, body = _post_json(f"{base}/api/ingest", ev, token="tk")
            assert st == 200 and body["ok"] and not body["deduped"], (q, st, body)
        # 深嵌套位置的正文键名仍必须拒(值放行不等于放弃红线)
        nested = _search("nest-1", "proj-v", "q", [])
        nested["layers"] = [{"repo": "r", "scanned": 1,
                             "matched": [{"id": "k1", "content": "偷偷塞正文"}]}]
        st, _ = _post_json(f"{base}/api/ingest", nested, token="tk")
        assert st == 400
        # 大小写变体键名也拒(早期实现靠 lower() 顺带挡住的, 递归版须显式保住)
        weird = _search("nest-2", "proj-v", "q", [])
        weird["filters"] = {"Text": "x"}
        st, _ = _post_json(f"{base}/api/ingest", weird, token="tk")
        assert st == 400
    finally:
        srv.shutdown()
        srv.server_close()


# ---- userconf(~/.kb/config.toml 最小子集) --------------------------------

def test_userconf_roundtrip(tmp_path, monkeypatch):
    from kb import userconf
    monkeypatch.setenv("KB_SERVE_URL", "")
    monkeypatch.delenv("KB_SERVE_URL", raising=False)
    monkeypatch.delenv("KB_SERVE_TOKEN", raising=False)
    monkeypatch.delenv("KB_INGEST_URL", raising=False)
    monkeypatch.delenv("KB_INGEST_TOKEN", raising=False)
    p = tmp_path / ".kb" / "config.toml"
    got = userconf.write_serve_config("http://kb.internal:4320", "s3cret", path=p)
    assert got == p and p.exists()
    text = p.read_text(encoding="utf-8")
    ingest_section = text.split("[ingest]")[1].split("[")[0]
    assert "url" in ingest_section and "token" not in ingest_section  # ingest 段无凭据
    url, tok = userconf.serve_target(p)
    assert (url, tok) == ("http://kb.internal:4320", "s3cret")
    iurl, itok = userconf.ingest_target(p)
    assert iurl == "http://kb.internal:4320" and itok == "s3cret"


def test_userconf_env_overrides_file(tmp_path, monkeypatch):
    from kb import userconf
    p = tmp_path / "config.toml"
    userconf.write_serve_config("http://file:1", "file-tok", path=p)
    monkeypatch.setenv("KB_INGEST_URL", "http://env:2")
    url, _ = userconf.ingest_target(p)
    assert url == "http://env:2"


def test_userconf_hash_in_values_survives_roundtrip(tmp_path):
    """§47 实锤: 旧读侧无条件 split('#'), 引号值里的 # 也当注释截 → 含 # 的
    URL 片段/令牌写进 config 再读出即损坏(静默截掉凭据尾巴, 401 无从排查)。"""
    from kb import userconf
    p = tmp_path / "config.toml"
    userconf.write_serve_config("http://kb.internal:4320/#board", "a#b#c", path=p)
    url, tok = userconf.serve_target(p)
    assert (url, tok) == ("http://kb.internal:4320/#board", "a#b#c")
    iurl, itok = userconf.ingest_target(p)
    assert (iurl, itok) == ("http://kb.internal:4320/#board", "a#b#c")


def test_userconf_handwritten_quoted_values_with_inline_comment(tmp_path):
    """手写配置的引号值: 引号内 # 属值, 闭引号后的 # 才是注释(写读对称契约)。"""
    from kb import userconf
    p = tmp_path / "config.toml"
    p.write_text('[serve]\nurl = "http://h/x#y"   # 行内注释应被剥\n'
                 'token = "p#q"\nplain = raw-val  # 无引号值 # 起为注释\n',
                 encoding="utf-8")
    cfg = userconf.read_config(p)
    assert cfg["serve"]["url"] == "http://h/x#y"
    assert cfg["serve"]["token"] == "p#q"
    assert cfg["serve"]["plain"] == "raw-val"


def test_userconf_quote_in_value_roundtrip(tmp_path):
    """§47 对称面: 旧写侧对值原样嵌入, token 含引号产出 `token = "a"b"` 损坏
    文件; 修复后写侧转义、读侧闭引号跳过转义对, 往返保真。"""
    from kb import userconf
    p = tmp_path / "config.toml"
    userconf.write_serve_config('http://h', 'a"b', path=p)
    url, tok = userconf.serve_target(p)
    assert (url, tok) == ("http://h", 'a"b')


def test_userconf_legacy_corrupted_file_degrades_empty(tmp_path):
    """旧版写坏的存量文件(引号未闭合)不得半解析出截断凭据——整体降级为空,
    消费方回退单人态/环境变量, 好文件不受影响。"""
    from kb import userconf
    p = tmp_path / "config.toml"
    p.write_text('[serve]\ntoken = "a"b"\nurl = "http://h"\n', encoding="utf-8")
    assert userconf.serve_target(p) == (None, None)


# ---- launcher(kb web 启动器): 拼 URL 必须百分号编码(§49) ------------------

def _qs_of(url: str) -> dict:
    """浏览器 URLSearchParams 同语义读参: # 起是 fragment 不进 query, + 解空格。"""
    from urllib.parse import parse_qs
    q = url.split("?", 1)[1].split("#", 1)[0] if "?" in url else ""
    return {k: v[-1] for k, v in parse_qs(q, keep_blank_values=True).items()}


def test_open_panel_team_token_special_chars_survive(monkeypatch):
    """§49 实锤: 旧 open_panel 用 f-string 拼 query, token 含 `+`(base64 常见)
    被前端解成空格、含 `&` 被劈成两参数、含 `#` 整段降为 fragment——打开即
    401 且静默。修复后值一律 percent-encode, 往返保真。"""
    from kb import launcher, userconf
    tok = "s3cr+tK=&x#y"
    monkeypatch.setattr(userconf, "serve_target",
                        lambda path=None: ("http://kb.internal:4320", tok))
    monkeypatch.setattr(launcher, "probe_http",
                        lambda base, token=None, timeout=1.5: True)
    url, mode = launcher.open_panel(4320, caller=None, no_browser=True)
    assert mode.startswith("team")
    assert _qs_of(url).get("token") == tok


def test_open_panel_degraded_serve_url_with_fragment_survives(monkeypatch):
    """降级横幅的 serve_url 值本身是 URL(第二十九轮后 `#` 已可合法配置):
    不编码则 `#` 起整段变 fragment, 横幅显示的地址被截残。"""
    from kb import launcher, userconf
    team = "http://kb.internal:4320/#board"
    monkeypatch.setattr(userconf, "serve_target",
                        lambda path=None: (team, "t1"))
    monkeypatch.setattr(launcher, "probe_http",
                        lambda base, token=None, timeout=1.5: False)
    monkeypatch.setattr(launcher, "probe_port",
                        lambda port, host="127.0.0.1", timeout=0.4: True)
    url, mode = launcher.open_panel(4320, caller="my project", no_browser=True)
    assert mode == "local-degraded"
    q = _qs_of(url)
    assert q.get("serve_url") == team
    assert q.get("caller") == "my project"   # 含空格的项目名同样保真


def test_join_qs_keeps_base_query_and_drops_fragment():
    """base 可配成带 query/fragment 的 URL: 原 query 原样保留在前, 新参数编码
    追加其后, fragment 丢弃(面板状态全走 query, 留着会挡住参数)。"""
    from kb.launcher import _join_qs
    out = _join_qs("http://h/base?a=1", [("token", "x y#z")])
    assert out == "http://h/base?a=1&token=x%20y%23z"
    out2 = _join_qs("http://h/base#frag", [("caller", "*")])
    assert out2 == "http://h/base?caller=%2A"      # 前端 URLSearchParams 解回 '*'
