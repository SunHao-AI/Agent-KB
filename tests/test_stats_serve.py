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
