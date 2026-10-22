"""FR-1.2 指标口径唯一实现(kb.stats)的口径回归 + serve 服务端点冒烟。"""
import json
import threading
import urllib.error
import urllib.request

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


def test_callers_stale_detection():
    S = [_search("t1", "fresh", "v", ["k1"], ts="2026-10-19T10:00:00+08:00"),
         _search("t2", "dead", "v", ["k1"], ts="2026-01-01T10:00:00+08:00")]
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
    (tmp_path / "traces").mkdir()
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
    """token 态回归守护: 面板所有 /api/* 请求(fetch 与 EventSource)必须经 apiUrl() 统一
    注入 token, 禁止手拼 — 实测踩坑: stats/feed/health 曾漏带导致 token 态静默 401 全空。"""
    import re
    from pathlib import Path
    from kb.serve import _asset_dir
    html = (Path(_asset_dir()) / "index.html").read_text(encoding="utf-8")
    bad = [m.group(0)[:70] for m in
           re.finditer(r"(?:fetch|EventSource)\(\s*(`[^`]*`|'[^']*')", html)
           if "/api/" in m.group(0)]
    assert not bad, f"面板 /api/* 请求未经 apiUrl() 手拼 URL(须走 apiUrl 注入 token): {bad}"
    assert "function apiUrl(" in html, "apiUrl() 统一注入器必须存在"


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
