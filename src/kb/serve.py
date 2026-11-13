"""kb serve — 观测服务端(PRD FR-2.1)。

职责(唯一聚合点):
- 监听 traces/*.jsonl 增量(mtime+size 轮询, 1s) → SSE 广播新事件;
- REST 出数一律经 kb.stats(FR-1.2 口径唯一实现), 客户端零计算;
- 边界: 只读、默认仅 127.0.0.1; 非本机绑定必须带 token(FR-2.5 红线);
- 与写侧解耦: 本服务任何故障不影响埋点落盘(它只是读侧消费者)。

单人态与团队态共用本实现, 差别仅 bind/token 参数; ingest 上报口属 B-4, 未实现。
"""
from __future__ import annotations

import datetime as dt
import hmac
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from queue import Empty, Queue
from urllib.parse import parse_qs, urlparse

from kb import metrics as kbmetrics
from kb import stats, trace as kbtrace

_POLL_SEC = 1.0
_SSE_KEEPALIVE_SEC = 15.0

# 质量面缓存(见 _quality_one): 按库根分桶——--repos 联邦聚合后单份全局缓存
# 会被第一个库的签名锁死, 其余库每次全量重扫 due_review。每桶同时缓存五类
# "条目清单"(_quality_rows), 供 /api/quality/entries 下钻: 数字与清单同源同一次
# 扫描, 点开的条数与卡上显示的数字不可能对不上。
_QUALITY_CACHE: dict[str, dict] = {}

# 全库字符量缓存(键=库根, 值=(index 签名, 统计结果)): 用于"检索开销 ÷ 全库规模"
# 的 baseline 对照。不缓存则每 2s 轮询重读全部正文(本仓实测 208 条 / 48 万字)。
_KB_CHARS_CACHE: dict[str, tuple[tuple[int, int], dict]] = {}

# 质量分类(下钻 kind)= 面板五张可点卡片。清单不设上限: 单库量级只有数百条
# (2026-11-02 实测三库合计 544 条), 截断反而制造"卡上 228 / 清单 200"的新对不上。
_QUALITY_KINDS = ("draft", "speculative", "needs_scope", "no_tags", "due")


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
        # 隔离清单也是口径输入: 改了清单必须让缓存失效, 否则面板要重启 serve
        # 才认新规则(观测工具的"改了不生效"会被读成"规则没起作用")。
        q = d / kbtrace.QUARANTINE_FILE
        try:
            st = q.stat()
            parts.append(f"{q.name}:{st.st_mtime_ns}:{st.st_size}")
        except OSError:
            parts.append(f"{q.name}:none")
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
        # "启动前已存在"用启动时目录快照判定, 不用 st_ctime>=time.time() 时钟比对
        # (2026-10-29 实测该比对受 ctime 粒度混叠, 启动前毫秒级刚写的文件 200 次里
        # 131 次被误判为新文件回放; spider_live 同款缺陷同批修复)
        d0 = kbtrace.traces_dir(self.root)
        self._preexisting = {f.name for f in d0.glob("*.jsonl")} if d0.exists() else set()
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
            # tail 语义: 只消费到最后一个换行符, 半行留在偏移之外等下次轮询。
            # 早期实现把偏移推进到 chunk 末尾, 半行 JSONDecodeError 被 continue 吞掉
            # 后偏移已越过该字节 → 行补全后 watcher 视为已消费, 该事件在 SSE 实时流
            # 里**永久漏推**(文件本身完整, 刷新页面才看得到; 第十二轮走查实测)。
            # 二进制读: st_size/偏移/截断检测全用同一字节口径(文本模式 tell 是
            # opaque cookie, 手工推进不可靠); \n 不会出现在 UTF-8 多字节序列内部,
            # 按换行截断后整行解码必合法。
            with f.open("rb") as fh:
                fh.seek(pos)
                chunk = fh.read()
            cut = chunk.rfind(b"\n")
            if cut < 0:
                continue  # 至今没有完整行(写入中), 偏移原地不动
            self._offsets[f] = pos + cut + 1
            for ln in chunk[:cut].decode("utf-8", "replace").splitlines():
                try:
                    ev = json.loads(ln)
                except json.JSONDecodeError:
                    continue
                # 非对象行(JSON 数组/标量)无 .get → 会让 watcher 线程崩掉, 全局停推(§26)
                if isinstance(ev, dict) and ev.get("kind") in ("search", "get"):
                    kbtrace._coerce(ev, [], f.name)   # 与读侧同口径归一, 否则脏事件直达前端
                    self._broadcast(ev)

    def _is_new(self, f: Path) -> bool:
        return f.name not in self._preexisting


_LOGIN_WINDOW = 60.0
_LOGIN_MAX_FAILS = 5
_LOGIN_MAX_IPS = 256
_COOKIE_ATTRS = "Path=/; HttpOnly; SameSite=Lax"


def _same_secret(a: str, b: str) -> bool:
    """常量时间比较(非 ASCII 也安全): 避免逐字符短路泄露令牌前缀。"""
    try:
        return hmac.compare_digest(a, b)
    except TypeError:
        return hmac.compare_digest(a.encode("utf-8"), b.encode("utf-8"))


class _Handler(BaseHTTPRequestHandler):
    server_version = "kb-serve/1"

    # ---- 基础设施 -------------------------------------------------------
    def log_message(self, *a):  # 静音默认 stderr 访问日志
        pass

    def _send(self, code: int, body: bytes, ctype: str, cache: str = "no-store",
              extra: dict | None = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", cache)
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200, extra: dict | None = None) -> None:
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", extra=extra)

    def _ip(self) -> str:
        return self.client_address[0] if self.client_address else "?"

    def _authorized(self) -> bool:
        srv = self.server  # type: ignore[attr-defined]
        tok = srv.token
        if not tok:
            return True
        # E1: 会话票据优先——面板启动时用一次性 ticket 换 HttpOnly cookie, 之后
        # 所有请求(含 SSE)凭 cookie 过鉴权, token 不再常驻 URL(浏览器历史/
        # Referer/分享链接都会泄露 query 里的明文 token)。
        ck = self.headers.get("Cookie", "")
        for part in ck.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "kb_tk" and v in srv.tickets:
                return True
        got = self.headers.get("Authorization", "")
        if got.startswith("Bearer "):
            got = got[7:]
        elif not got:  # SSE(EventSource)不能带自定义头 → query 传 token(兜底路径)
            got = parse_qs(urlparse(self.path).query).get("token", [""])[0]
        self._auth_retry = 0
        if not got:
            # 无凭据(匿名轮询/过期 cookie)不计失败: 否则面板 2s 轮询会把本机 IP
            # 锁死, 用户连登录卡都打不开。只有"猜了令牌"才算一次失败。
            return False
        wait = self._login_wait(srv, self._ip())
        if wait:
            self._auth_retry = wait
            return False
        if _same_secret(got, tok):
            self._clear_login_fail(srv, self._ip())
            return True
        self._record_login_fail(srv, self._ip())
        return False

    def _auth_deny(self) -> None:
        """鉴权失败的统一出口: 限流中回 429(+Retry-After), 否则 401。"""
        wait = getattr(self, "_auth_retry", 0)
        if wait:
            self._json({"error": "too many attempts"}, 429,
                       extra={"Retry-After": str(wait)})
        else:
            self._json({"error": "unauthorized"}, 401)

    def do_POST(self) -> None:  # noqa: N802
        srv = self.server  # type: ignore[attr-defined]
        u = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        # 回任何错误(404/401/400)前必须先把请求体读干: 客户端(http.client)是
        # "头一段、体一段"两次 write, 若服务端没读 body 就回 401 并 close, 晚到
        # 的 body 落在已关连接上 → 服务端 OS 回 RST(Windows), 把刚写出的 401
        # 响应字节一并吞掉——客户端拿到 ConnectionResetError(10054)而非干净 401
        # (全量套件 test_ingest 偶发 flaky ~1/8, 探针受控时序复现; RFC 9110 亦
        # 要求带体请求出错先 drain 再关)。读上限与合法路径同 64KB, 超限不读直接
        # 关(防放大)。
        raw = b""
        if 0 < n <= 64 * 1024:
            raw = self.rfile.read(n)
        elif n > 64 * 1024:
            self.close_connection = True
        if u.path == "/api/session":
            self._login(raw, n)
            return
        if u.path == "/api/logout":
            self._logout()
            return
        if u.path != "/api/ingest":
            self._json({"error": "not found"}, 404)
            return
        if not self._authorized():
            self._auth_deny()
            return
        if n <= 0 or n > 64 * 1024:
            self._json({"error": "bad body"}, 400)
            return
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
        # 身份字段必须是 str(第三十四轮走查 §52): trace_id/id 参与幂等 key 元组
        # (非 str 不可哈希 → handler 线程 TypeError → 连接被重置, §26 同构但在写侧);
        # caller_repo/ts 会原样落盘, 读侧 by_caller.setdefault(dict) 同样炸 500。
        # 写侧 fail-loud 拒收(400)好过脏数据入团队账本后读侧反复崩。
        for k in ("trace_id", "id", "caller_repo", "layer", "source", "ts"):
            v = ev.get(k)
            if v is not None and not isinstance(v, str):
                self._json({"error": f"{k} must be string or null"}, 400)
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

    def _login(self, raw: bytes, n: int) -> None:
        """JSON body 登录(spec §4.2): 令牌只进请求体, 不进 URL/历史/Referer。"""
        srv = self.server  # type: ignore[attr-defined]
        if not srv.token:
            self._json({"error": "auth disabled"}, 409)
            return
        if n <= 0:
            self._json({"error": "bad body"}, 400)
            return
        if n > 4096:
            self._json({"error": "body too large"}, 413)
            return
        try:
            body = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json({"error": "bad json"}, 400)
            return
        tok = body.get("token") if isinstance(body, dict) else None
        remember = bool(body.get("remember")) if isinstance(body, dict) else False
        ip = self.client_address[0] if self.client_address else "?"
        wait = self._login_wait(srv, ip)
        if wait:
            self._json({"error": "too many attempts"}, 429,
                       extra={"Retry-After": str(wait)})
            return
        if not isinstance(tok, str) or not _same_secret(tok, srv.token):
            self._record_login_fail(srv, ip)
            self._json({"error": "bad token"}, 403)
            return
        with srv.login_lock:
            srv.login_fail.pop(ip, None)
        import secrets as _secrets
        t = _secrets.token_urlsafe(32)
        with srv.login_lock:
            # 满池淘汰单张而非全清: 全清会让所有设备/标签页同时静默掉线
            if len(srv.tickets) >= 64:
                srv.tickets.pop()
            srv.tickets.add(t)
        ck = f"kb_tk={t}; {_COOKIE_ATTRS}"
        if remember:
            ck += "; Max-Age=2592000"
        self._json({"ok": True, "remember": remember}, extra={"Set-Cookie": ck})

    def _login_wait(self, srv, ip: str) -> int:
        """返回需要等待的整秒; 0 表示放行。只清理/统计, 不改写超出窗口的记录。"""
        now = time.monotonic()
        with srv.login_lock:
            times = [t for t in srv.login_fail.get(ip, [])
                     if now - t < _LOGIN_WINDOW]
            if times:
                srv.login_fail[ip] = times
            else:
                srv.login_fail.pop(ip, None)
            if len(times) >= _LOGIN_MAX_FAILS:
                return max(1, int(_LOGIN_WINDOW - (now - times[0])) + 1)
            return 0

    def _record_login_fail(self, srv, ip: str) -> None:
        now = time.monotonic()
        with srv.login_lock:
            times = [t for t in srv.login_fail.get(ip, [])
                     if now - t < _LOGIN_WINDOW]
            times.append(now)
            srv.login_fail[ip] = times
            if len(srv.login_fail) > _LOGIN_MAX_IPS:
                srv.login_fail.pop(next(iter(srv.login_fail)), None)

    def _clear_login_fail(self, srv, ip: str) -> None:
        """令牌验证成功即清零: 一次正确登录/请求即可解除本机 IP 的限流。"""
        with srv.login_lock:
            srv.login_fail.pop(ip, None)

    def _logout(self) -> None:
        """撤销当前 cookie 的票据(spec §4.2): 只影响本会话, 其他设备不动。"""
        srv = self.server  # type: ignore[attr-defined]
        ck = self.headers.get("Cookie", "")
        for part in ck.split(";"):
            k, _, v = part.strip().partition("=")
            if k == "kb_tk" and v:
                with srv.login_lock:
                    srv.tickets.discard(v)
        self._json({"ok": True}, extra={
            "Set-Cookie": f"kb_tk=; {_COOKIE_ATTRS}; Max-Age=0"})

    # ---- 路由 -----------------------------------------------------------
    def do_GET(self) -> None:  # noqa: N802
        srv = self.server  # type: ignore[attr-defined]
        u = urlparse(self.path)
        if u.path == "/healthz":
            self._json({"ok": True, "schema": kbtrace.SCHEMA,
                        "auth": bool(srv.token)})
            return
        if u.path == "/":
            # 静态壳免鉴权(不含数据, 数据全在 /api/* 逐个鉴权): 否则无 token 用户
            # 看到浏览器裸 JSON 401, 前端专门的"需要访问令牌"友好横幅永远没机会渲染(§24 实测)
            self._send(200, srv._panel_html().encode("utf-8"),
                       "text/html; charset=utf-8")
            return
        if u.path == "/api/session":
            # E1: 会话票据交换——ticket(即 serve token)换 HttpOnly 会话 cookie。
            # ticket 由 `kb web` 拼在打开浏览器的初始 URL 里(只进浏览器一次),
            # 面板随即请求本端点, 之后 URL 即被 replaceState 洗掉 token——
            # 历史/Referer/分享链接不再带明文。交换不设一次性作废: 团队态是常驻
            # serve 多标签共用 token, 一次性会破坏重开/多标签; ticket 可交换的
            # 能力本就以持有 token 为前提, 不新增重放面。
            tokq = parse_qs(urlparse(self.path).query).get("ticket", [""])[0]
            ip = self._ip()
            if srv.token:
                wait = self._login_wait(srv, ip)
                if wait:
                    self._json({"error": "too many attempts"}, 429,
                               extra={"Retry-After": str(wait)})
                    return
            if not srv.token or not _same_secret(tokq, srv.token):
                # 非空 ticket 才计失败: 面板缺参探测不该把 IP 锁死
                if srv.token and tokq:
                    self._record_login_fail(srv, ip)
                self._json({"error": "bad ticket"}, 403)
                return
            self._clear_login_fail(srv, ip)
            import secrets as _secrets
            t = _secrets.token_urlsafe(32)
            # 满池淘汰单张而非全清: 全清会让所有设备/标签页同时静默掉线
            if len(srv.tickets) >= 64:
                srv.tickets.pop()
            srv.tickets.add(t)
            self._json({"ok": True}, extra={
                "Set-Cookie": f"kb_tk={t}; Path=/; HttpOnly; SameSite=Lax"})
            return
        if not self._authorized():
            self._auth_deny()
            return
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        # since/until 入口校验(§58, CLI --since 同族): 字符串比较式日期过滤对
        # 非法值静默滤空——面板拿到"全空数据"却显示为合法空态(假空), 与"该窗口
        # 真没数据"不可区分。fail-loud 400, 前端窗口参数由 sinceDate() 生成合法
        # ISO 日期, 正常流量零影响。
        for k in ("since", "until"):
            v = q.get(k)
            if v:
                try:
                    dt.date.fromisoformat(v)
                except ValueError:
                    self._json({"error": f"{k} must be YYYY-MM-DD, got {v!r}"}, 400)
                    return
        # feed limit 入口校验(§58 同族第四处, 第四十二轮): 此前 `int(q.get(...))`
        # 把非数值参数炸成 500 internal——客户端错误伪装成服务器故障, 面板只能
        # 显示"internal: ValueError"无从自助。fail-loud 400 指明参数与期望格式。
        if "limit" in q:
            try:
                int(q["limit"])
            except ValueError:
                self._json({"error": f"limit must be an integer, got {q['limit']!r}"}, 400)
                return
        try:
            if u.path == "/api/health":
                self._json({"ok": True, "schema": kbtrace.SCHEMA,
                            "traces_dir": str(kbtrace.traces_dir(srv.root)),
                            "exists": kbtrace.traces_dir(srv.root).exists(),
                            "spider_ready": srv.spider.ready()})
            elif u.path == "/api/stats":
                # 缓存键含 raw: 剔噪口径与原始口径是两份不同结果, 互串会串出口径错乱
                ck = ("stats", q.get("caller", ""), q.get("since", ""), q.get("until", ""),
                      q.get("raw", ""))
                self._json(srv.agg.get(ck, lambda: _stats_payload(srv, q)))
            elif u.path == "/api/callers":
                # 矩阵统计列随窗口(与同屏 KPI 同口径, §29); 活跃性在 stats 内保持全量
                # 剔噪同口径: 合成 caller 不配占矩阵一行(它们不是"项目")
                ck = ("callers", q.get("since", ""), q.get("raw", ""))
                self._json(srv.agg.get(ck, lambda: stats.callers(
                    _read(srv, q)[0], since=q.get("since") or None)))
            elif u.path == "/api/quality":
                self._json(_quality_payload(srv))
            elif u.path == "/api/quality/entries":
                # B3 下钻: 点质量卡数字才拉清单(不进常驻轮询)。参数错 400 而非空清单,
                # 空清单会被面板读成"该分类真的没有条目"——与假空数据同罪(§58 同族)。
                try:
                    self._json(_quality_entries(srv, q))
                except (ValueError, OSError) as exc:
                    self._json({"error": str(exc)}, 400)
                    return
            elif u.path == "/api/entry":
                # Q8: 清单行点开原文。id 不在该库 → 404(与参数错 400 分开: 前者是
                # "查无此条"的合法答案, 后者是调用方拼错)。
                try:
                    self._json(_entry_source(srv, q))
                except FileNotFoundError as exc:
                    self._json({"error": str(exc)}, 404)
                    return
                except (ValueError, OSError) as exc:
                    self._json({"error": str(exc)}, 400)
                    return
            elif u.path == "/api/trend":
                ck = ("trend", q.get("caller", ""), q.get("since", ""), q.get("until", ""),
                      q.get("raw", ""))
                self._json(srv.agg.get(ck, lambda: _trend_payload(srv, q)))
            elif u.path == "/api/metrics":
                # 周快照直连不走 agg 缓存: AggCache._sig 只盯 traces/*.jsonl,
                # 新生成的 .json 快照不会使其失效 —— 走缓存会把"刚生成的上周快照"
                # 藏到 serve 重启为止。读盘是目录级小 IO, 面板轮询扛得住。
                snaps, warns = kbmetrics.load_snapshots(srv.root)
                points = []
                for s in snaps:
                    m = s.get("metrics") or {}
                    zh = s.get("zero_hit") or {}
                    la = s.get("latency") or {}
                    points.append({"week": s["week"], "since": s.get("since"),
                                   "until": s.get("until"),
                                   "searches": m.get("searches"),
                                   "hit_rate": m.get("hit_rate"),
                                   "consume_rate": m.get("consume_rate"),
                                   # 该周是否完全落在消费埋点前(整周不绘制); 部分覆盖
                                   # (跨起点的那周)仍绘制, 用 consume_partial 标注下界。
                                   "consume_tracked": (s.get("until") or "") >=
                                   stats.CONSUME_TRACKING_SINCE,
                                   "consume_partial": bool(m.get("pre_tracking_searches"))
                                   and (s.get("until") or "") >= stats.CONSUME_TRACKING_SINCE,
                                   "digest_rate": zh.get("digest_rate"),
                                   "p50_ms": la.get("p50_ms"),
                                   "cold_start": bool(m.get("cold_start"))})
                self._json({"snapshots": points, "warns": warns,
                            # 消费率可采集起点: 之前周次的 consume_rate 是"CLI 读全文
                            # 未埋点"的产物, 折线必须断开而不是当 0 画(见 stats 常量)。
                            "consume_tracked_from": stats.CONSUME_TRACKING_SINCE})
            elif u.path == "/api/export":
                # B4: JSON 附件下载, 面板转成 CSV。走 agg 缓存会返回同一份对象,
                # 导出低频且要即时性, 直连实现函数
                try:
                    data = _export_payload(srv, q)
                except ValueError as exc:
                    self._json({"error": str(exc)}, 400)
                    return
                kind = q.get("kind") or "zero"
                self._json(data, extra={
                    "Content-Disposition": f'attachment; filename="kb-{kind}.json"'})
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
                # 窗口参数与 /api/stats 同口径(A2): feed 快照跟随 since/until,
                # 切窗口时列表与 KPI 不再两口径。缓存键必须含窗口, 否则 7 天/全时互串;
                # 也必须含 raw(剔噪口径同理: 实测 raw=1 的响应会串给紧随其后的默认
                # 请求, 检索流整屏跳回含噪声数据)。
                # 窗口内真实总数经 X-Total-Count 头返回: limit 截断后 body 长度不再
                # 等于窗口总数, 面板需要它才能区分"窗口里就这么多"与"被 500 条截断"
                # (2026-11-02 实测: 7 天窗 830 条 / 全时 1110 条, 截断后两者都显 500,
                #  切窗口计数纹丝不动, 窗口口径改动在 UI 上完全不可见)。
                ck = ("feed", q.get("caller", ""), q.get("limit", "50"),
                      q.get("since", ""), q.get("until", ""), q.get("raw", ""))
                rows, total = srv.agg.get(ck, lambda: _feed_payload(srv, q))
                # Expose-Headers: 自定义响应头默认不暴露给跨源 fetch(回放页正是
                # serve 起的另一端口), 不声明则对端 headers.get 恒 null, "窗口共 N"
                # 会静默退回旧显示
                self._json(rows, extra={"X-Total-Count": str(total),
                                        "Access-Control-Expose-Headers": "X-Total-Count"})
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
                 default_caller: str | None, quiet: bool = False,
                 extra_repos: dict[str, Path] | None = None):
        super().__init__(addr, _Handler)
        self.root = Path(root)
        self.token = token
        self.default_caller = default_caller
        # A5: `--repos name=path` 声明的额外可观测库(路径是"kb 根", 其下有 kb/)
        self.extra_repos = dict(extra_repos or {})
        # ingest 幂等去重(有界内存, 超限整体重置; git 账本仍按 trace_id 收敛)
        self.seen_ingest: set[tuple] = set()
        self.ingest_cap = 50_000
        self.watcher = TraceWatcher(self.root, quiet=quiet)
        self.spider = SpiderBridge()
        self.agg = AggCache(self.root)
        self._html: str | None = None      # E2: 热加载缓存(见 _panel_html)
        self._html_sig: tuple | None = None
        # E1: 一次性 ticket → 会话票据池(有界, 超限清最旧重建; 重启即失效可接受)
        self.tickets: set[str] = set()
        # 登录失败限流(spec §4.3): 每 IP 60s 滑动窗口, 有界防内存滥用
        self.login_fail: dict[str, list[float]] = {}
        self.login_lock = threading.Lock()
        self._panel_html()

    def _panel_html(self) -> str:
        """面板 HTML(mtime+size 签名热加载, E2)。

        旧实现在 __init__ 读死: 改 index.html 必须重启 serve——实测一个下午被咬
        两次(改完验到的还是旧版, 甚至一度把"源码带语法错误"误判成"旧构建")。
        面板是自用观测工具, 每次请求一次 stat() 的成本可忽略; 读取失败回退旧
        缓存(编辑保存的瞬时半写态不该让面板 500)。
        """
        f = _asset_dir() / "index.html"
        try:
            st = f.stat()
            sig = (st.st_mtime_ns, st.st_size)
            if sig != self._html_sig or self._html is None:
                self._html = f.read_text(encoding="utf-8")
                self._html_sig = sig
        except OSError:
            if self._html is None:
                raise
        return self._html

    @staticmethod
    def filter_caller(searches, gets, q):
        c = q.get("caller") or ""
        if not c or c in ("*", "all"):
            return searches, gets
        return ([s for s in searches if s.get("caller_repo") == c],
                [g for g in gets if g.get("caller_repo") == c])

    def resolve_caller(self, q) -> str | None:
        """caller=all(2026-11-02): 面板"跨项目"开关——榜单(零命中/热门)本就跨
        caller 聚合, 单项目视图的检索流却只看本项目, 于是别的项目的零命中点
        "追因"必然落空(实测)。all = 显式要"不过滤 caller 但仍是单项目视图"
        (区别于 *: 联邦视图, 后者还会换整套 UI 与 default_caller 语义)。"""
        c = q.get("caller") or self.default_caller or ""
        return None if c in ("*", "all") else (c or None)


def _quality_one(root: Path) -> dict:
    """单库质量面(库本身好不好), 与检索面(用得好不好)并列的第二个观测维度。

    只读 index.jsonl / index.draft.jsonl 两个生成物, 不扫正文目录, 成本恒定。
    到期复核数需逐条读 front-matter(due_review 要 review_by/updated), 故按索引
    文件签名**分库**缓存 —— 质量是低频变动量, 不该跟检索面板一样每次刷新全仓扫。

    root 语义 = "kb 根"(其下有 kb/ 目录): Agent-KB 主仓传仓根, 业务仓传其
    docs/ 目录(flysee-video-setting 的 `docs/kb/`)。口径唯一, 与 query/index
    对 root 的解释一致, --repos 复用同一函数。
    """
    root = Path(root)
    if not (root / "kb").is_dir():
        raise ValueError(f"{root} 下没有 kb/ 目录(不是 kb 根)")
    key = str(root.resolve()).lower()
    idx = root / "kb" / "index.jsonl"
    dj = root / "kb" / "index.draft.jsonl"
    try:
        sig = tuple((f.stat().st_mtime_ns, f.stat().st_size) for f in (idx, dj))
    except OSError:
        sig = None
    hit = _QUALITY_CACHE.get(key)
    if sig is not None and hit and hit["sig"] == sig:
        return hit["data"]

    from kb.query import _records
    recs = _records(root)
    rows, due_ok = _quality_rows(root, recs)
    data = {
        "repo": _kb_repo_label(root),
        "total": len(recs),
        "by_status": _count(recs, "status"),
        "by_confidence": _count(recs, "confidence"),
        "by_type": _count(recs, "type"),
        "by_scope": _count(recs, "scope"),
        # 五计数一律取清单长度(B3): 卡上的数字与点开的条目出自同一次扫描的同一个
        # 谓词, 结构上不可能对不上(旧实现各自 sum(), 改一处口径就得同步改两处)。
        "draft_backlog": len(rows["draft"]),
        "speculative": len(rows["speculative"]),
        "needs_scope": len(rows["needs_scope"]),
        "no_tags": len(rows["no_tags"]),
        "due_review": len(rows["due"]) if due_ok else None,  # 库缺失: 不猜, 前端显 —
        "index_fresh": _index_fresh(root),
    }
    if sig is not None:
        _QUALITY_CACHE[key] = {"sig": sig, "data": data, "rows": rows, "root": root}
    return data


def _entry_row(r: dict, **extra) -> dict:
    """下钻清单行: 面板够辨认(id 虚拟展示由前端负责)+ 能直达文件(path)。"""
    return {"id": r.get("id", ""), "title": r.get("title", ""),
            "status": r.get("status", ""), "confidence": r.get("confidence", ""),
            "scope": r.get("scope", ""), "tags": r.get("tags") or [],
            "updated": r.get("updated", ""), "path": r.get("path", ""), **extra}


def _quality_rows(root: Path, recs: list[dict]) -> tuple[dict[str, list], bool]:
    """五类条目清单(下钻事实源)。due 需逐条读 front-matter, 其余四类纯索引字段。

    due 桶以 due_review() 的判定为准(它才认 review_by/复核周期兜底), 再用索引行
    补 path 等字段; 索引里没有的(索引漂移)仍按 due_review 的最小字段给出——
    漏一条清单比清单少个 path 更糟。
    """
    rows = {
        "draft": [_entry_row(r) for r in recs if r.get("status") == "draft"],
        "speculative": [_entry_row(r) for r in recs
                        if r.get("confidence") == "speculative"],
        "needs_scope": [_entry_row(r) for r in recs
                        if "needs-scope-review" in (r.get("tags") or [])],
        "no_tags": [_entry_row(r) for r in recs if not (r.get("tags") or [])],
        "due": [],
    }
    ok = False
    try:
        from kb.query import due_review
        by_id = {r.get("id"): r for r in recs}
        for d in due_review(root, dt.date.today()):
            base = by_id.get(d.get("id"))
            rows["due"].append(_entry_row(base, review_by=d.get("review_by", ""))
                               if base else _entry_row(
                                   {"id": d.get("id", ""), "title": d.get("title", "")},
                                   review_by=d.get("review_by", "")))
        ok = True
    except OSError:
        ok = False
    return rows, ok


def _quality_targets(srv: "ServeServer") -> dict[str, Path]:
    """可下钻的库: 显示名 → kb 根(本 serve root + --repos 声明的库)。"""
    out = {_kb_repo_label(srv.root): Path(srv.root)}
    for name, path in (srv.extra_repos or {}).items():
        out[str(name).lower()] = Path(path)
    return out


def _resolve_repo(srv: "ServeServer", name: str) -> Path:
    """按名定位库根: 先配名(--repos 的 name), 再目录标签。

    清单行的 repo 列显示 `_kb_repo_label(path)`(如 `--repos biz=D:\\x\\docs` 显示
    `x`), 而 targets 的键是声明名 `biz`——只按 keys 查, 拿着列值点"原文"必 400。
    两种名字都是面板上可见的, 都该能解析。歧义(一个名字同时是配名和别库标签)
    取配名(更具体)。
    """
    targets = _quality_targets(srv)
    n = (name or "").strip().lower()
    if n in targets:
        return targets[n]
    for root in targets.values():
        if _kb_repo_label(root) == n:
            return root
    raise ValueError(f"unknown repo {name!r}, known: {sorted(set(targets) | {_kb_repo_label(r) for r in targets.values()})}")


def _quality_entries(srv: "ServeServer", q: dict) -> dict:
    """B3 下钻: `GET /api/quality/entries?kind=draft&repo=<名|all>` → 该分类条目清单。

    只走按需点击, 不进 /api/quality 常驻轮询响应(五类清单全量内联会把每 2s 的
    轮询载荷放大几十倍)。kind/repo 拼错必须 400(fail-loud), 静默回空清单会被
    读成"这个分类真的没有条目"。

    `repo=all` = 联邦合计口径(面板卡上是 N 库合计数字, 清单必须同样跨库拼, 否则
    "卡上 8 / 点开 3"——数字与清单对不上正是本次要修的问题)。跨库行带 repo 字段
    供面板分列。
    """
    kind = (q.get("kind") or "").strip()
    if kind not in _QUALITY_KINDS:
        raise ValueError(f"kind must be one of {list(_QUALITY_KINDS)}, got {kind!r}")
    targets = _quality_targets(srv)
    name = (q.get("repo") or _kb_repo_label(srv.root)).strip().lower()
    if name not in targets and name != "all":
        raise ValueError(f"unknown repo {q.get('repo')!r}, known: {sorted(targets) + ['all']}")
    picked = targets if name == "all" else {name: targets[name]}
    rows: list[dict] = []
    total = 0
    skipped: dict[str, str] = {}
    for label, root in picked.items():
        try:
            data = _quality_one(root)
        except (OSError, ValueError) as exc:
            # 联邦合计口径里坏库本就被 _quality_payload 剔出 total, 下钻跟着剔
            # 才对得上; 单库下钻则让它冒出来(400), 不能对着坏库回空清单。
            if name != "all":
                raise
            skipped[label] = str(exc)
            continue
        cached = _QUALITY_CACHE.get(str(Path(root).resolve()).lower())
        if cached is not None:             # 常态: 与卡上数字同一份 rows
            rws = cached["rows"]
        else:  # 索引文件缺失(sig=None, 不缓存): 现扫一次, 口径仍是同一函数
            from kb.query import _records
            rws, _ = _quality_rows(root, _records(root))
        lst = rws.get(kind, [])
        total += len(lst)
        if name == "all":
            rows += [dict(r, repo=data["repo"]) for r in lst]
        else:
            rows += [dict(r) for r in lst]   # 复制: 下面要往行里写使用度
    # Q11: 每行附使用度(hits/reads/last), 打通"质量清单 → 使用情况"。用请求的
    # caller/窗口口径(_read 已按 raw 剔噪)——"哪些 draft 天天被命中该优先审"是相对
    # 当前视图问的。dict(r) 复制: rows 来自质量缓存且喂卡上计数, 改到缓存对象会污染。
    us, ug, _uw, _un, _ub = _read(srv, q)
    us, ug = srv.filter_caller(us, ug, q)
    usage = stats.usage_by_id(stats.in_window(us, q.get("since"), q.get("until")),
                              stats.in_window(ug, q.get("since"), q.get("until")))
    for r in rows:
        u = usage.get(r.get("id")) or {"hits": 0, "reads": 0, "last": ""}
        r["hits"], r["reads"], r["last_used"] = u["hits"], u["reads"], u["last"]
    # 按使用度倒序: 最该优先处理的(天天被检索却没审)排最前
    rows.sort(key=lambda r: (-r["hits"], -r["reads"], r.get("id", "")))
    return {"repo": name, "kind": kind, "total": total, "skipped": skipped,
            "window": {"since": q.get("since"), "until": q.get("until")},
            "rows": rows}


def _entry_source(srv: "ServeServer", q: dict) -> dict:
    """Q8: `GET /api/entry?id=&repo=` → 条目原文(观测的下一步动作是"看看这条到底啥情况")。

    路径经索引 id 反查(_find_path 只认 index.jsonl 里的 path), 不接受任意路径参数,
    不引入目录穿越面; 与 serve 整体只读口径一致。找不到回 404 语义由调用方处理。
    """
    eid = (q.get("id") or "").strip()
    if not eid:
        raise ValueError("id is required")
    from kb.query import get_entry
    if q.get("repo"):
        root = _resolve_repo(srv, q["repo"])
        body = get_entry(root, eid)
        if body is None:
            raise FileNotFoundError(f"{eid} not in repo {q['repo']}")
        return {"repo": _kb_repo_label(root), "id": eid, "markdown": body}
    # R8: 不带 repo = 跨库找(原文里 related 的 kb-id 大概率不在当前库; 让调用方
    # 逐库试是把这个判断推给每个前端)。本库优先, 再按 --repos 声明序。
    for label, root in _quality_targets(srv).items():
        body = get_entry(root, eid)
        if body is not None:
            return {"repo": _kb_repo_label(root), "id": eid, "markdown": body}
    raise FileNotFoundError(f"{eid} not found in any repo")


def _kb_repo_label(root: Path) -> str:
    """库显示名: kb 根向上一级目录名(docs/ → 业务仓名), 与 caller_repo 同源可比。

    直接拿 kb 根目录名会得到 `docs` / `Agent-KB` 这类和 traces 里 caller_repo
    (业务仓名)对不上的标签, 面板 by_repo 就没法和检索面的项目名互相印证。
    """
    root = Path(root).resolve()
    name = root.name.lower()
    if name in ("kb", "docs"):
        return root.parent.name.lower()
    return name


def _quality_payload(srv: "ServeServer") -> dict:
    """质量面聚合(A5): 本 serve root + `--repos name=path` 显式声明的库。

    口径边界(必须随数据一起给前端): serve 无法凭 trace 推断业务仓的磁盘位置
    ——trace 只有 caller_repo 名字。所以**只聚合显式配置的库**, 未配置的按
    traces 里出现过的 caller 列入 `uncovered`, 面板如实标"未覆盖"。宁缺勿错,
    不拿本库数字冒充全局, 也不猜路径。
    """
    main = _quality_one(srv.root)
    repos = [dict(main, repo=main["repo"], root=str(Path(srv.root).resolve()))]
    errs: dict[str, str] = {}
    for name, path in (srv.extra_repos or {}).items():
        try:
            d = _quality_one(path)
            repos.append(dict(d, repo=name, root=str(Path(path).resolve())))
        except (OSError, ValueError) as exc:
            errs[name] = str(exc)
    # 覆盖度: traces 里出现过的 caller 中, 哪些没有对应的质量数据
    covered = {r["repo"].lower() for r in repos}
    try:
        seen = stats.callers(_read(srv)[0])
        callers_seen = [c.get("caller") for c in seen if c.get("caller")]
    except OSError:
        callers_seen = []
    uncovered = sorted({c.lower() for c in callers_seen} - covered)
    out = dict(main)
    if len(repos) > 1:
        # 顶栏 KPI 是"合计"口径(面板标注"联邦 N 库"), 逐库数字在 repos 里分列。
        # due_review 任一库读不到(None)则合计也显 —, 不拿部分和冒充全量。
        due = [r["due_review"] for r in repos]
        out.update(
            total=sum(r["total"] for r in repos),
            draft_backlog=sum(r["draft_backlog"] for r in repos),
            speculative=sum(r["speculative"] for r in repos),
            needs_scope=sum(r["needs_scope"] for r in repos),
            no_tags=sum(r["no_tags"] for r in repos),
            due_review=None if any(v is None for v in due) else sum(due),
            index_fresh=all(r["index_fresh"] is not False for r in repos),
        )
    return {**out, "repos": repos, "uncovered": uncovered, "errors": errs}


def _count(recs: list[dict], key: str) -> dict:
    out: dict[str, int] = {}
    for r in recs:
        v = r.get(key) or "?"
        out[v] = out.get(v, 0) + 1
    return out


def _index_fresh(root: Path) -> bool | None:
    """索引是否与正文同步(kb index --check 同判据)。异常返回 None = 未知。"""
    try:
        from kb.index import check_indexes, resolve_repo_name
        return check_indexes(root, repo_name=resolve_repo_name(root))
    except Exception:
        return None


def _read(srv: "ServeServer", q: dict | None = None):
    """读侧统一入口: 账本原文 → 合成语料剔噪(P0-1)。

    默认剔, `?raw=1` 回到含噪声原始口径(自查判据是否误伤真实仓)。返回
    (searches, gets, warns, dropped_count, dropped_callers)。

    剔噪两级(见 kb.stats.denoise_full): caller 级启发式 + `traces/synthetic-ids.json`
    事件级隔离清单。为什么读侧剔而不是改账本: traces/ 已按每日定时任务提交进 git,
    历史污染改写不得(账本是事实源, 改写=伪造观测数据); 规则与误判面见
    stats.synthetic_callers / trace.load_quarantine。
    """
    s, g, warns = kbtrace.read_traces(root=srv.root)
    rules, qwarns = kbtrace.load_quarantine(srv.root)
    warns = warns + qwarns
    if (q or {}).get("raw") in ("1", "true", "yes"):
        return s, g, warns, 0, []
    s, g, audit = stats.denoise_full(s, g, rules)
    return s, g, warns, audit["dropped"], audit["callers"]


def _feed_payload(srv: "ServeServer", q: dict):
    """返回 (快照行, 窗口内总数)。

    total = "caller 过滤 + 窗口过滤"之后的检索事件数(与 feed_events 的前两道
    过滤同口径, caller 用 resolve_caller 与 feed_events 同源的取值), 而非被
    limit 截断后的行数。面板用它如实标注"本窗口共 N 条 · 已载入 M 条", 用户
    才能区分"窗口里就这么多"与"被 500 条截断"(实测 7 天窗 830/全时 1110 都
    截成 500 时, 切窗口计数纹丝不动)。
    """
    all_s, all_g, _, _n, _bad = _read(srv, q)
    since, until = q.get("since") or None, q.get("until") or None
    c = srv.resolve_caller(q)
    total = len(stats.in_window(
        [s for s in all_s if not c or s.get("caller_repo") == c], since, until))
    rows = stats.feed_events(all_s, all_g, caller=c,
                             limit=int(q.get("limit", 50)), since=since, until=until,
                             offset=int(q.get("offset", 0) or 0))
    return rows, total


def _kb_chars(root: Path) -> dict:
    """本库全库字符量: 给"检索开销"一个可核对的分母, 否则 saved_chars 只是差值不是节省。

    只认 index.jsonl 里的 path(索引是唯一事实源), 不 glob 正文目录; 结果按索引
    签名分库缓存, 轮询成本恒定。读不出正文的行跳过并按 entries 计数, 不猜大小。
    """
    root = Path(root)
    idx = root / "kb" / "index.jsonl"
    try:
        sig = (idx.stat().st_mtime_ns, idx.stat().st_size)
        raw = idx.read_text(encoding="utf-8")
    except OSError:
        return {"entries": 0, "kb_chars": 0, "index_chars": 0}
    key = str(root.resolve()).lower()
    hit = _KB_CHARS_CACHE.get(key)
    if hit and hit[0] == sig:
        return hit[1]
    total = n = 0
    for ln in raw.splitlines():
        try:
            rel = json.loads(ln)["path"]
            total += len((root / rel).read_text(encoding="utf-8"))
            n += 1
        except (ValueError, KeyError, TypeError, OSError):
            continue
    try:
        index_chars = len((root / "kb" / "INDEX.md").read_text(encoding="utf-8"))
    except OSError:
        index_chars = 0
    data = {"entries": n, "kb_chars": total, "index_chars": index_chars}
    _KB_CHARS_CACHE[key] = (sig, data)
    return data


def _stats_payload(srv: "ServeServer", q: dict) -> dict:
    """FR-1.2 出数(口径全在 kb.stats), 经 AggCache 按 trace 签名缓存。

    榜单(top_consumed/zero_hits)与 KPI 同窗口: UI 空态文案自己写着
    "窗口内", 实现却数全量 → 切窗口后 KPI 与榜单两口径(§29 实测)。

    `synthetic_count`/`synthetic_callers` 随数据一起给前端: 剔噪是改口径不是抹
    事件, 用户要能看到被剔了多少、剔的是哪些 caller(否则指标静默变好=黑箱)。
    """
    # synthetic_count 必须是**当前 caller+窗口口径**下的剔噪数: 全账本全 caller 的
    # 数与同屏窗口口径的 KPI 对不上号会被质疑真实性(2026-11-02 走查实测: 标注 157
    # vs 两态 KPI 差 70)。取"同一过滤条件下两口径事件数之差", 与卡面数字严格可
    # 对账; 全账本数另给 synthetic_total。一次 read_traces 两口径共用(读盘是这里
    # 的主要成本, 不走 _read 二次读)。
    s0, g0, warns = kbtrace.read_traces(root=srv.root)
    rules, qwarns = kbtrace.load_quarantine(srv.root)
    warns = warns + qwarns
    raw = q.get("raw") in ("1", "true", "yes")
    # 两级剔噪分开计数, 面板才能说清"剔的多少是猜的、多少是登记的":
    # ① caller 级启发式(synthetic_callers) ② 事件级隔离清单(traces/synthetic-ids.json)
    s_heur, g_heur, n_heur, bad_heur = stats.denoise(s0, g0)
    s_q, g_q, q_audit = stats.quarantine_events(s_heur, g_heur, rules)
    s, g = (s0, g0) if raw else (s_q, g_q)
    bad_syn = [] if raw else sorted(bad_heur)
    sa, ga = srv.filter_caller(s0, g0, q)
    sh, gh = srv.filter_caller(s_heur, g_heur, q)
    s, g = srv.filter_caller(s, g, q)
    since, until = q.get("since"), q.get("until")

    def _wc(pair) -> int:
        return (len(stats.in_window(pair[0], since, until))
                + len(stats.in_window(pair[1], since, until)))

    # 两边都先过窗口再相减: s 只过了剔噪+caller(全窗口), 直接拿"窗口内原始数 −
    # 全窗口剔噪数"在窄窗口(如聚焦单日)会减穿成负数(2026-11-02 回归实测 -812)。
    n_syn_win = 0 if raw else _wc((sa, ga)) - _wc((sh, gh))
    n_q_win = 0 if raw else _wc((sh, gh)) - _wc((s, g))
    n_syn_all = 0 if raw else n_heur
    q_total = 0 if raw else q_audit["dropped"]
    # Q4: 审计明细恒基于原始账本(s0/g0)计算, 两口径都给——raw=1 的用途就是自查误伤,
    # 若 raw 下也留空, 逃生门等于没有。denoise_detail 内部对空 bad 直接返回 []。
    detail = stats.denoise_detail(s0, g0)
    return {"kpi": stats.aggregate(s, g, since=since, until=until),
            # baseline 只描述本 serve root 的库, 与 caller 过滤无关; 前端按"本库"标注。
            "baseline": _kb_chars(srv.root),
            "synthetic_count": n_syn_win, "synthetic_total": n_syn_all,
            "synthetic_callers": bad_syn, "synthetic_detail": detail,
            # 隔离清单口径(事件级): 与 synthetic_* 并列单列, 混算会掩盖"哪些是登记的"
            "quarantine_count": n_q_win, "quarantine_total": q_total,
            "quarantine_detail": q_audit["detail"],
            "top_consumed": stats.top_consumed(stats.in_window(s, since, until),
                                               stats.in_window(g, since, until), limit=10),
            "dead_weight": stats.dead_weight(stats.in_window(s, since, until),
                                             stats.in_window(g, since, until), limit=10),
            "zero_hits": stats.zero_hit_board(stats.in_window(s, since, until), limit=10),
            "latency": stats.latency(s, since=since, until=until),
            "warns": warns}


def _trend_payload(srv: "ServeServer", q: dict) -> dict:
    """B1 趋势: 逐日 检索数/命中数/耗时中位数, 与 KPI 同 caller 过滤。

    面板此前全是窗口聚合快照——命中率变好变坏、零命中词是新出现还是老口子,
    快照读不出来。逐日序列由 aggregate 顺带产出(by_day), 这里补每日均耗时。
    """
    s, g, warns, _n, _bad = _read(srv, q)
    s, g = srv.filter_caller(s, g, q)
    since, until = q.get("since"), q.get("until")
    k = stats.aggregate(s, g, since=since, until=until)
    days: dict[str, list[int]] = {}
    for ev in s:
        d = str(ev.get("ts", ""))[:10]
        dm = ev.get("duration_ms")
        if isinstance(dm, (int, float)):
            days.setdefault(d, []).append(int(dm))
    out = []
    for row in k["by_day"]:
        v = sorted(days.get(row["day"], []))
        # R7: 每日 P95 与 KPI 的 latency 同一分位算法(stats.latency 的 pctl:
        # ceil(x/100*n)-1 序位)。排查"某天毛刺"要看的就是 P95, 只有中位数会把
        # 长尾完全抹平。
        p95 = (v[min(len(v) - 1, -(-95 * len(v) // 100) - 1)] if v else None)
        out.append({**row,
                    "median_ms": v[len(v) // 2] if v else None,
                    "p95_ms": p95})
    return {"days": out, "cold_start": k["cold_start"], "warns": warns}


def _export_payload(srv: "ServeServer", q: dict) -> object:
    """B4 导出: 榜单/检索流/趋势的 JSON 下载(浏览器端拼 CSV 由面板负责)。

    kind=zero|consumed|feed|quality|trend; 与面板显示同一实现出口, 导出的
    数字与看到的一致(周报场景; 之前只能截图)。
    """
    kind = q.get("kind") or "zero"
    s, g, _w, _n, _bad = _read(srv, q)
    s, g = srv.filter_caller(s, g, q)
    since, until = q.get("since"), q.get("until")
    if kind == "zero":
        return stats.zero_hit_board(stats.in_window(s, since, until), limit=1000)
    if kind == "consumed":
        return stats.top_consumed(stats.in_window(s, since, until),
                                  stats.in_window(g, since, until), limit=1000)
    if kind == "dead":
        return stats.dead_weight(stats.in_window(s, since, until),
                                 stats.in_window(g, since, until), limit=1000)
    if kind == "feed":
        # T3: 导出全量(窗口内所有事件), 不再硬编码 2000 截断——观测数据千条级,
        # 2000 上限会在长窗口下静默截断且无任何声明。1e6 仅作极端异常兜底。
        rows, _ = _feed_payload(srv, {**q, "limit": "1000000"})
        return rows
    if kind == "trend":
        return _trend_payload(srv, q)["days"]
    if kind == "quality":
        # Q3: 质量面来自索引, 与 caller/窗口无关。此前面板把 caller/since 一并拼给
        # 所有 kind, 参数被静默丢弃 = 导出方以为按窗口筛了(§58 假数据同族)。要么
        # 不传, 要么显式拒绝。
        ignored = [p for p in ("caller", "since", "until") if q.get(p)]
        if ignored:
            raise ValueError(f"kind=quality ignores {ignored} (索引口径, 与 caller/窗口无关)")
        return _quality_payload(srv)["repos"]
    raise ValueError(f"unknown kind: {kind}")


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


def parse_repos(items: list[str] | None) -> dict[str, Path]:
    """解析 `--repos name=path`(可重复)。name 用 caller_repo 口径(小写仓名),
    面板 by_repo 才能与检索面项目名互认。非法写法直接 ValueError 交由启动处报错。"""
    out: dict[str, Path] = {}
    for it in items or []:
        name, sep, path = it.partition("=")
        name = name.strip().lower()
        if not sep or not name or not path.strip():
            raise ValueError(f"--repos 需要 name=path 形式, 收到: {it!r}")
        out[name] = Path(path.strip()).expanduser()
    return out


def resolve_token(cli_token: str | None = None) -> str | None:
    """令牌解析唯一入口(spec §4.1): --token > KB_SERVE_TOKEN > 用户配置。

    配置来源是 `~/.kb/config.toml [serve].token`, 由 userconf.serve_target 统一读取;
    缺省 None 表示本机单人态免鉴权(行为不变)。
    """
    from kb import userconf
    return cli_token or userconf.serve_target()[1] or None


def run(root: Path | None = None, *, port: int = 4320, bind: str = "127.0.0.1",
        token: str | None = None, default_caller: str | None = None,
        quiet: bool = False, extra_repos: dict[str, Path] | None = None) -> None:
    bind = resolve_bind(bind, token)
    root = Path(root) if root else kbtrace.kb_root()
    srv = ServeServer((bind, port), root, token, default_caller, quiet=quiet,
                      extra_repos=extra_repos)
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

    ap = argparse.ArgumentParser(prog="kb serve")
    ap.add_argument("--repo", default=None, help="Agent-KB 仓根, 默认本包所在仓")
    ap.add_argument("--port", type=int, default=4320)
    ap.add_argument("--bind", default="127.0.0.1")
    ap.add_argument("--token", default=None,
                    help="访问令牌; 缺省读 KB_SERVE_TOKEN 或 ~/.kb/config.toml [serve].token")
    ap.add_argument("--default-caller", default=None, help="单项目视图默认项目(kb web 代拉起时传入)")
    ap.add_argument("--repos", action="append", metavar="NAME=PATH", default=None,
                    help="额外纳入质量面的库(PATH 指向其 kb 根, 如 "
                         "..\\flysee-video-setting\\docs), 可重复(A5 质量联邦)")
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
        extra = parse_repos(a.repos)
    except ValueError as exc:
        print(f"kb serve: {exc}")
        return 2
    try:
        run(Path(a.repo) if a.repo else None, port=a.port, bind=a.bind,
            token=resolve_token(a.token),
            default_caller=a.default_caller, extra_repos=extra)
    except ValueError as exc:
        print(f"kb serve: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
