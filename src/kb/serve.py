"""kb serve — 观测服务端(PRD FR-2.1)。

职责(唯一聚合点):
- 监听 traces/*.jsonl 增量(mtime+size 轮询, 1s) → SSE 广播新事件;
- REST 出数一律经 kb.stats(FR-1.2 口径唯一实现), 客户端零计算;
- 边界: 只读、默认仅 127.0.0.1; 非本机绑定必须带 token(FR-2.5 红线);
- 与写侧解耦: 本服务任何故障不影响埋点落盘(它只是读侧消费者)。

单人态与团队态共用本实现, 差别仅 bind/token 参数; ingest 上报口属 B-4, 未实现。
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue
from urllib.parse import parse_qs, urlparse

from kb import stats, trace as kbtrace

_POLL_SEC = 1.0
_SSE_KEEPALIVE_SEC = 15.0


class AggCache:
    """聚合响应缓存: 按 traces 目录签名(mtime_ns+size 汇总)失效 + 单飞合并发车。

    观测面板是"≤2s 轮询式读"场景, 同参数重复请求占绝对多数; 并发打进来时
    只让一个线程真算, 其余等结果 — 消除 ThreadingHTTPServer 下 GIL 串行放大。
    正确性: append-only 语义下任何写入必然改变 size → 签名变 → 缓存自动失效,
    因此无需 TTL 也不会读到旧数据(读侧最新事件即刻可见)。
    """

    KEYS = 64

    def __init__(self, root: Path):
        self.root = Path(root)
        self._lock = threading.Lock()
        self._memo: dict[tuple, tuple[str, object]] = {}
        self._keys: dict[tuple, threading.Lock] = {}

    def _sig(self) -> str:
        d = kbtrace.traces_dir(self.root)
        if not d.exists():
            return "none"
        parts = []
        for f in sorted(d.glob("*.jsonl")):
            try:
                st = f.stat()
                parts.append(f"{f.name}:{st.st_mtime_ns}:{st.st_size}")
            except OSError:
                parts.append(f"{f.name}:gone")
        return "|".join(parts)

    def get(self, key: tuple, compute):
        """命中走全局锁(O(1)); 未命中只锁本 key — 冷算 callers 不阻塞已缓存的 feed。"""
        sig = self._sig()
        with self._lock:
            hit = self._memo.get(key)
            if hit and hit[0] == sig:
                return hit[1]
            klock = self._keys.setdefault(key, threading.Lock())
        with klock:  # 单飞: 同 key 并发只算一次
            with self._lock:  # 双检(等锁期间同 key 可能已算好)
                hit = self._memo.get(key)
                if hit and hit[0] == sig:
                    return hit[1]
            val = compute()
            with self._lock:
                if len(self._memo) >= self.KEYS:  # 参数组合有界(含 query 抖动)
                    self._memo.clear()
                    self._keys.clear()
                self._memo[key] = (sig, val)
                self._keys.pop(key, None)
            return val


class SpiderBridge:
    """回放桥: 懒启动克隆仓 MCP, trace_id → previewUrl(整页回放, 面板新标签打开)。

    首次请求才 spawn node; 缺 Node/克隆依赖时记住错误不再重试(失败面收敛一次)。
    会话缓存有界(≤15, 克隆进程上限 20): 超限先 close 最旧会话, 防 create 被拒。
    """

    CAP = 15

    def __init__(self):
        import threading
        from collections import OrderedDict
        self._mcp = None
        self._dead: str | None = None
        self._urls: OrderedDict[str, tuple[str, str]] = OrderedDict()
        self._lock = threading.Lock()
        self._ready: bool | None = None

    def ready(self) -> bool:
        """全屏回放桥是否就绪(轻量探测: node + 克隆仓 + mcp 依赖), 不启动子进程。
        结果缓存, 供 /api/health 暴露给面板决定"默认 iframe 还是 SVG 降级"。"""
        if self._ready is None:
            import shutil
            try:
                from kb.spider_live import find_spider_home
                home = find_spider_home()
                self._ready = bool(shutil.which("node")) and \
                    (home / "mcp" / "node_modules").exists()
            except (FileNotFoundError, OSError):
                self._ready = False
        return self._ready

    def _alive(self) -> bool:
        """桥子进程存活(未 spawn 或已退出都算不存活; 测试注入的假桥无 .p 视为存活)。"""
        p = getattr(self._mcp, "p", None)
        return self._mcp is not None and (p is None or p.poll() is None)

    def replay_url(self, record: dict, tid: str) -> str:
        with self._lock:
            if self._urls and not self._alive():
                self._urls.clear()   # 桥进程死过: 其会话 URL 全指向死进程, 一并作废
            if tid in self._urls:
                self._urls.move_to_end(tid)
                return self._urls[tid][1]
            # _dead 只对"起桥前的依赖缺失"永久短路(_mcp 仍 None); 运行期桥进程死亡
            # (被杀/崩溃→管道写入 [Errno 22])不是配置问题, 清引用下次自动重生。
            if self._dead and self._mcp is None:
                raise RuntimeError(self._dead)
            try:
                if not self._alive():
                    if self._mcp is not None:
                        try:
                            self._mcp.close()
                        except OSError:
                            pass
                        self._mcp = None
                    from kb.spider_live import SpiderMcp, find_spider_home
                    self._mcp = SpiderMcp(find_spider_home())
                res = self._mcp.tool("spider_import_session", {"record": record})
                url, sid = res.get("previewUrl"), res.get("id")
                if not url or not sid:
                    raise RuntimeError(f"spider import 无 previewUrl: {res}")
                try:  # 默认自动重播+循环(imported 会话允许 loop); 失败不影响回放本身
                    self._mcp.tool("spider_control_playback", {
                        "sessionId": sid,
                        "command": {"loop": True, "action": "restart"}})
                except RuntimeError:
                    pass
            except (RuntimeError, FileNotFoundError, OSError) as exc:
                self._dead = str(exc)
                raise
            self._urls[tid] = (sid, url)
            while len(self._urls) > self.CAP:  # 逐旧腾位(关闭失败不阻断)
                _, (old_sid, _) = self._urls.popitem(last=False)
                try:
                    self._mcp.tool("spider_close_session", {"sessionId": old_sid})
                except RuntimeError:
                    pass
            return url


class TraceWatcher(threading.Thread):
    """traces/*.jsonl 增量读取(mtime+size 变化才重读), 新事件入队广播。"""

    def __init__(self, root: Path, quiet: bool = False):
        super().__init__(daemon=True)
        self.root = Path(root)
        self.subscribers: list[Queue] = []
        self._lock = threading.Lock()
        self._offsets: dict[Path, int] = {}
        self._birth = time.time()
        self._quiet = quiet
        self.warns: list[str] = []

    def subscribe(self) -> Queue:
        q: Queue = Queue()
        with self._lock:
            self.subscribers.append(q)
        return q

    def unsubscribe(self, q: Queue) -> None:
        with self._lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def _broadcast(self, ev: dict) -> None:
        with self._lock:
            for q in self.subscribers:
                q.put(ev)

    def run(self) -> None:
        while True:
            try:
                self._tick()
            except Exception as exc:  # 读侧故障静默续跑(红线: 观测不拖垮任何事)
                if not self._quiet:
                    self.warns.append(f"watcher: {exc}")
            time.sleep(_POLL_SEC)

    def _tick(self) -> None:
        d = kbtrace.traces_dir(self.root)
        if not d.exists():
            return
        for f in sorted(d.glob("*.jsonl")):
            size = f.stat().st_size
            pos = self._offsets.get(f)
            if pos is None:
                # 首见文件: 启动后出现的新文件从头播, 启动前已存在的只记偏移不回灌
                self._offsets[f] = 0 if self._is_new(f) else size
                continue
            if size <= pos:
                if size < pos:  # 文件被截断/重写: 重置
                    self._offsets[f] = 0
                continue
            with f.open("r", encoding="utf-8") as fh:
                fh.seek(pos)
                chunk = fh.read()
                self._offsets[f] = fh.tell()
            for ln in chunk.splitlines():
                try:
                    ev = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                # 非对象行(JSON 数组/标量)无 .get → 会让 watcher 线程崩掉, 全局停推(§26)
                if isinstance(ev, dict) and ev.get("kind") in ("search", "get"):
                    kbtrace._coerce(ev, [], f.name)   # 与读侧同口径归一, 否则脏事件直达前端
                    self._broadcast(ev)

    def _is_new(self, f: Path) -> bool:
        return f.stat().st_ctime >= self._birth


class _Handler(BaseHTTPRequestHandler):
    server_version = "kb-serve/1"

    # ---- 基础设施 -------------------------------------------------------
    def log_message(self, *a):  # 静音默认 stderr 访问日志
        pass

    def _send(self, code: int, body: bytes, ctype: str, cache: str = "no-store") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _authorized(self) -> bool:
        tok = self.server.token  # type: ignore[attr-defined]
        if not tok:
            return True
        got = self.headers.get("Authorization", "")
        if got.startswith("Bearer "):
            got = got[7:]
        elif not got:  # SSE(EventSource)不能带自定义头 → query 传 token
            got = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        return got == tok

    def do_POST(self) -> None:  # noqa: N802
        srv = self.server  # type: ignore[attr-defined]
        u = urlparse(self.path)
        if u.path != "/api/ingest":
            self._json({"error": "not found"}, 404)
            return
        if not self._authorized():
            self._json({"error": "unauthorized"}, 401)
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        if n <= 0 or n > 64 * 1024:
            self._json({"error": "bad body"}, 400)
            return
        raw = self.rfile.read(n)
        try:
            ev = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json({"error": "bad json"}, 400)
            return
        # 红线延伸: ingest 口同样拒收正文键名(与 CI 键名校验同口径)
        if not isinstance(ev, dict) or ev.get("kind") not in ("search", "get"):
            self._json({"error": "kind must be search|get"}, 400)
            return
        # 红线延伸: ingest 口拒收"正文键名"(PRD: 正文键名拒收, 与 CI 同口径)。
        # 只递归查 dict 键名, 不查值——早期实现对整坨 JSON 扫 "content"/"text"/"body"
        # 子串, 把值也扫了: query="content" 这类合法检索词序列化成 "query": "content"
        # 含 "content" → 误判 400, 叠加客户端 _post_ingest 静默吞异常, 团队账本
        # 永久缺该事件且无告警(第十轮走查实测)。
        def _has_body_key(o) -> bool:
            if isinstance(o, dict):
                return any((isinstance(k, str) and k.lower() in ("body", "content", "text"))
                           or _has_body_key(v) for k, v in o.items())
            if isinstance(o, list):
                return any(_has_body_key(x) for x in o)
            return False

        if _has_body_key(ev):
            self._json({"error": "body/content keys not allowed"}, 400)
            return
        key = (ev.get("kind"), ev.get("trace_id"), ev.get("id"), ev.get("ts"))
        if key in srv.seen_ingest:  # trace_id 幂等: 重发不再落盘/不再广播
            self._json({"ok": True, "deduped": True})
            return
        if len(srv.seen_ingest) >= srv.ingest_cap:
            srv.seen_ingest.clear()
        srv.seen_ingest.add(key)
        # ingest=False: 服务端落盘不得再向上中继(防两实例互推成环)
        kbtrace.append_event(ev, srv.root, ingest=False)
        self._json({"ok": True, "deduped": False})

    # ---- 路由 -----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        srv = self.server  # type: ignore[attr-defined]
        u = urlparse(self.path)
        if u.path == "/healthz":
            self._json({"ok": True, "schema": kbtrace.SCHEMA})
            return
        if u.path == "/":
            # 静态壳免鉴权(不含数据, 数据全在 /api/* 逐个鉴权): 否则无 token 用户
            # 看到浏览器裸 JSON 401, 前端专门的"需要访问令牌"友好横幅永远没机会渲染(§24 实测)
            self._send(200, srv.index_html.encode("utf-8"),
                       "text/html; charset=utf-8")
            return
        if not self._authorized():
            self._json({"error": "unauthorized"}, 401)
            return
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/api/health":
                self._json({"ok": True, "schema": kbtrace.SCHEMA,
                            "traces_dir": str(kbtrace.traces_dir(srv.root)),
                            "exists": kbtrace.traces_dir(srv.root).exists(),
                            "spider_ready": srv.spider.ready()})
            elif u.path == "/api/stats":
                ck = ("stats", q.get("caller", ""), q.get("since", ""), q.get("until", ""))
                self._json(srv.agg.get(ck, lambda: _stats_payload(srv, q)))
            elif u.path == "/api/callers":
                # 矩阵统计列随窗口(与同屏 KPI 同口径, §29); 活跃性在 stats 内保持全量
                ck = ("callers", q.get("since", ""))
                self._json(srv.agg.get(ck, lambda: stats.callers(
                    kbtrace.read_traces(root=srv.root)[0], since=q.get("since") or None)))
            elif u.path.startswith("/api/replay/"):
                tid = u.path[len("/api/replay/"):]
                rec = _replay_record(srv.root, tid)
                if rec is None:
                    self._json({"error": f"trace {tid} not found"}, 404)
                    return
                self._json(rec)
            elif u.path.startswith("/api/spider/"):
                tid = u.path[len("/api/spider/"):]
                rec = _replay_record(srv.root, tid)
                if rec is None:
                    self._json({"error": f"trace {tid} not found"}, 404)
                    return
                try:
                    self._json({"previewUrl": srv.spider.replay_url(rec, tid)})
                except (RuntimeError, FileNotFoundError, OSError) as exc:
                    # 缺 Node/克隆依赖不是 500: 面板拿 message 引导降级(原生 SVG 回放仍在)
                    self._json({"error": str(exc)}, 503)
            elif u.path == "/api/feed":
                ck = ("feed", q.get("caller", ""), q.get("limit", "50"))
                self._json(srv.agg.get(ck, lambda: stats.feed_events(
                    *srv.filter_caller(*kbtrace.read_traces(root=srv.root)[:2], q),
                    caller=srv.resolve_caller(q), limit=int(q.get("limit", 50)))))
            elif u.path == "/api/stream":
                self._sse(srv.watcher, srv.resolve_caller(q))
            else:
                self._json({"error": "not found"}, 404)
        except BrokenPipeError:
            pass
        except Exception as exc:   # 数据/参数引发的意外: 回 500 而不是让连接裸断, 面板才能提示(§26)
            self._json({"error": f"internal: {type(exc).__name__}: {exc}"}, 500)

    def _sse(self, watcher: TraceWatcher, caller: str | None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        q = watcher.subscribe()
        try:
            while True:
                try:
                    ev = q.get(timeout=_SSE_KEEPALIVE_SEC)
                except Empty:
                    self.wfile.write(b": ka\n\n")
                    self.wfile.flush()
                    continue
                if caller and ev.get("caller_repo") != caller:
                    continue
                name = ev.get("kind", "event")
                self.wfile.write(f"event: {name}\ndata: "
                                 f"{json.dumps(ev, ensure_ascii=False)}\n\n".encode())
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            watcher.unsubscribe(q)


class ServeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, addr, root: Path, token: str | None,
                 default_caller: str | None, quiet: bool = False):
        super().__init__(addr, _Handler)
        self.root = Path(root)
        self.token = token
        self.default_caller = default_caller
        # ingest 幂等去重(有界内存, 超限整体重置; git 账本仍按 trace_id 收敛)
        self.seen_ingest: set[tuple] = set()
        self.ingest_cap = 50_000
        self.watcher = TraceWatcher(self.root, quiet=quiet)
        self.spider = SpiderBridge()
        self.agg = AggCache(self.root)
        self.index_html = (_asset_dir() / "index.html").read_text(encoding="utf-8")

    @staticmethod
    def filter_caller(searches, gets, q):
        c = q.get("caller") or ""
        if not c or c == "*":
            return searches, gets
        return ([s for s in searches if s.get("caller_repo") == c],
                [g for g in gets if g.get("caller_repo") == c])

    def resolve_caller(self, q) -> str | None:
        c = q.get("caller") or self.default_caller or ""
        return None if c == "*" else (c or None)


def _stats_payload(srv: "ServeServer", q: dict) -> dict:
    """FR-1.2 出数(口径全在 kb.stats), 经 AggCache 按 trace 签名缓存。

    榜单(top_consumed/top_queries/zero_hits)与 KPI 同窗口: UI 空态文案自己写着
    "窗口内", 实现却数全量 → 切窗口后 KPI 与榜单两口径(§29 实测)。
    """
    s, g, warns = kbtrace.read_traces(root=srv.root)
    s, g = srv.filter_caller(s, g, q)
    since, until = q.get("since"), q.get("until")
    return {"kpi": stats.aggregate(s, g, since=since, until=until),
            "top_consumed": stats.top_consumed(stats.in_window(s, since, until),
                                               stats.in_window(g, since, until), limit=10),
            "top_queries": stats.top_queries(stats.in_window(s, since, until), limit=10),
            "zero_hits": stats.zero_hit_board(stats.in_window(s, since, until), limit=10),
            "warns": warns}


def _asset_dir() -> Path:
    return Path(__file__).resolve().parent / "web"


def _replay_record(root: Path, tid: str) -> dict | None:
    """trace_id → 完整可导入 record(仅喂本 trace 的 get, 已读态才不越界)。"""
    s, g, _ = kbtrace.read_traces(root=root)
    search = next((e for e in s if e.get("trace_id") == tid), None)
    if search is None:
        return None
    from kb.spider_export import to_record
    return to_record(search, [e for e in g if e.get("trace_id") == tid])


def resolve_bind(bind: str | None, token: str | None) -> str:
    """红线: 非本机绑定必须带 token, 否则拒绝启动。返回规范化 bind。"""
    bind = bind or "127.0.0.1"
    if bind not in ("127.0.0.1", "localhost", "::1") and not token:
        raise ValueError("非本机绑定必须提供 --token(或 KB_SERVE_TOKEN); 拒绝无鉴权裸奔")
    return bind


def run(root: Path | None = None, *, port: int = 4320, bind: str = "127.0.0.1",
        token: str | None = None, default_caller: str | None = None,
        quiet: bool = False) -> None:
    bind = resolve_bind(bind, token)
    root = Path(root) if root else kbtrace.kb_root()
    srv = ServeServer((bind, port), root, token, default_caller, quiet=quiet)
    srv.watcher.start()
    print(f"kb serve on http://{bind}:{port} (root={root}, auth={'on' if token else 'off'})")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os

    ap = argparse.ArgumentParser(prog="kb serve")
    ap.add_argument("--repo", default=None, help="Agent-KB 仓根, 默认本包所在仓")
    ap.add_argument("--port", type=int, default=4320)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--token", default=None, help="团队态访问令牌(亦可用 KB_SERVE_TOKEN)")
    ap.add_argument("--default-caller", default=None, help="单项目视图默认项目(kb web 代拉起时传入)")
    ap.add_argument("--install-autostart", action="store_true",
                    help="注册系统服务常驻(幂等, 见 kb.autostart)")
    ap.add_argument("--uninstall-autostart", action="store_true",
                    help="撤销 --install-autostart 注册的系统服务")
    a = ap.parse_args(argv)
    if a.install_autostart or a.uninstall_autostart:
        from kb import autostart
        try:
            if a.uninstall_autostart:
                print(autostart.uninstall())
            else:
                print(autostart.install(
                    Path(a.repo).resolve() if a.repo
                    else kbtrace.kb_root(), a.port, a.bind, a.default_caller))
        except (RuntimeError, OSError) as exc:
            print(f"kb serve autostart: {exc}")
            return 1
        return 0
    try:
        run(Path(a.repo) if a.repo else None, port=a.port, bind=a.bind,
            token=a.token or os.environ.get("KB_SERVE_TOKEN") or None,
            default_caller=a.default_caller)
    except ValueError as exc:
        print(f"kb serve: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
