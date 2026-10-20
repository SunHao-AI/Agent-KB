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
                if ev.get("kind") in ("search", "get"):
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
        flat = json.dumps(ev, ensure_ascii=False).lower()
        if any(f'"{k}"' in flat for k in ("body", "content", "text")):
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
        if not self._authorized():
            self._json({"error": "unauthorized"}, 401)
            return
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                self._send(200, srv.index_html.encode("utf-8"),
                           "text/html; charset=utf-8")
            elif u.path == "/api/health":
                self._json({"ok": True, "schema": kbtrace.SCHEMA,
                            "traces_dir": str(kbtrace.traces_dir(srv.root)),
                            "exists": kbtrace.traces_dir(srv.root).exists()})
            elif u.path == "/api/stats":
                s, g, warns = kbtrace.read_traces(root=srv.root)
                s, g = srv.filter_caller(s, g, q)
                self._json({"kpi": stats.aggregate(s, g, since=q.get("since"),
                                                   until=q.get("until")),
                            "top_consumed": stats.top_consumed(s, g, limit=10),
                            "top_queries": stats.top_queries(s, limit=10),
                            "zero_hits": stats.zero_hit_board(s, limit=10),
                            "warns": warns})
            elif u.path == "/api/callers":
                s, _, _ = kbtrace.read_traces(root=srv.root)
                self._json(stats.callers(s))
            elif u.path == "/api/feed":
                s, g, _ = kbtrace.read_traces(root=srv.root)
                s, g = srv.filter_caller(s, g, q)
                self._json(stats.feed_events(s, g, caller=srv.resolve_caller(q),
                                             limit=int(q.get("limit", 50))))
            elif u.path == "/api/stream":
                self._sse(srv.watcher, srv.resolve_caller(q))
            else:
                self._json({"error": "not found"}, 404)
        except BrokenPipeError:
            pass

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


def _asset_dir() -> Path:
    return Path(__file__).resolve().parent / "web"


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
    a = ap.parse_args(argv)
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
