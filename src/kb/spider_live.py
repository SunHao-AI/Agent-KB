"""kb spider-live — trace → prompt-spider-ui 实时直播桥(PRD FR-2.4)。

驱动克隆仓(e:/prompt-spider-ui)的 stdio MCP(mcp/server.mjs): 监听本机
traces/*.jsonl 增量, 每条 search 事件开一个蜘蛛会话(项目层→code 绿,
通用层→model 橙, 外接源→ext 粉, 随后到达的 get→you 黄), 5s 无新 get 即 complete 定格。

依赖: Node 20+ 与克隆仓 `npm --prefix mcp ci`(缺失时给出明确指引后退出)。
桥是纯读侧消费者, 任何失败不影响检索/埋点/面板。
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

from kb import trace as kbtrace
from kb.spider_export import spider_id

COMPLETE_AFTER_SEC = 5.0     # search 后无新 get 即定格(可回放)
_POLL_SEC = 0.5

# route 四色语义(与面板一致): code=项目层, model=通用层, ext=外接源(B-1, PRD 指定
# #F34A87), you=已读消费
ROUTES = {"code": {"label": "项目层命中", "color": "#42D6A4"},
          "model": {"label": "通用层命中", "color": "#F28A76"},
          "ext": {"label": "外接源命中", "color": "#F34A87"},
          "you": {"label": "已读消费", "color": "#F0CA57"}}


COMMON_HOMES = [r"e:\Workplace\prompt-spider-ui",
                str(Path.home() / "Workplace" / "prompt-spider-ui")]


def find_spider_home(explicit: str | None = None) -> Path:
    """定位克隆仓根: --spider-home > KB_SPIDER_HOME > 常见同级目录。"""
    cands = [explicit, os.environ.get("KB_SPIDER_HOME"), *COMMON_HOMES]
    for c in cands:
        if c and (Path(c) / "mcp" / "server.mjs").exists():
            return Path(c)
    raise FileNotFoundError(
        "找不到 prompt-spider-ui 克隆(需含 mcp/server.mjs)。"
        "用 --spider-home <路径> 或设 KB_SPIDER_HOME; 并在克隆的 mcp/ 目录内执行 npm ci")


class SpiderMcp:
    """prompt-spider MCP 的最小 stdio JSON-RPC 客户端(不引第三方 SDK)。"""

    def __init__(self, home: Path):
        node = shutil.which("node")
        if not node:
            raise RuntimeError("需要 Node.js 20+(PATH 里找不到 node)")
        if not (home / "mcp" / "node_modules").exists():
            raise RuntimeError(f"依赖未装: 进入 {home / 'mcp'} 执行 npm ci")
        self.p = subprocess.Popen(
            [node, str(home / "mcp" / "server.mjs")],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, encoding="utf-8")
        self._id = 0
        self._lock = threading.Lock()
        self._rpc("initialize", {"protocolVersion": "2024-11-05",
                                 "capabilities": {},
                                 "clientInfo": {"name": "kb-spider-live", "version": "1"}})
        self._notify("notifications/initialized", {})

    def _send(self, msg: dict) -> None:
        with self._lock:
            assert self.p.stdin
            self.p.stdin.write(json.dumps(msg, ensure_ascii=False) + "\n")
            self.p.stdin.flush()

    def _rpc(self, method: str, params: dict) -> dict:
        self._id += 1
        rid = self._id
        self._send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
        assert self.p.stdout
        while True:  # 跳过通知, 等本请求的 id
            line = self.p.stdout.readline()
            if not line:
                raise RuntimeError("spider MCP 进程已退出")
            msg = json.loads(line)
            if msg.get("id") == rid:
                if msg.get("error"):
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def _notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def tool(self, name: str, args: dict) -> dict:
        res = self._rpc("tools/call", {"name": name, "arguments": args})
        txt = (res.get("content") or [{}])[0].get("text", "{}")
        try:
            return json.loads(txt)
        except json.JSONDecodeError:
            return {"raw": txt}

    def close(self) -> None:
        try:
            self.p.terminate()
        except OSError:
            pass


def event_to_updates(search: dict) -> tuple[dict, list[dict]]:
    """search 事件 → (会话 config, 事件列表)。route 映射见模块头。"""
    # `or []`: 手工/异客户端 trace 可写 returned/layers/ext=null(_coerce 只归一
    # returned 且调用方未必都过它), .get 默认值对"键存在但为 null"不生效
    returned = set(search.get("returned") or [])
    layers = search.get("layers") or []
    proj_repo = layers[0]["repo"] if layers else None
    events, seen = [], set()
    for ly in layers:
        for m in ly.get("matched", []):
            if m["id"] not in returned or m["id"] in seen:
                continue
            seen.add(m["id"])
            events.append({"id": spider_id(m["id"]),
                           "label": str(m.get("title") or m["id"])[:40],
                           "route": "code" if ly.get("repo") == proj_repo else "model",
                           "status": "running",
                           "detail": "hit: " + "+".join(m.get("hit_fields") or [])})
    for e in search.get("ext") or []:  # 外接源命中 → ext 分支色(粉), label 带源名
        for eid in e.get("hits", []):
            if eid not in seen:
                seen.add(eid)
                events.append({"id": spider_id(eid),
                               "label": f"外接 {e.get('source')}: {eid}"[:40],
                               "route": "ext", "status": "running",
                               "detail": f"source://{e.get('source')}"})
    q = search.get("query") or "-"
    cfg = {"title": f"KB 直播 {search.get('caller_repo', '?')}"[:80],
           "subtitle": f"query: {q} · {len(events)} 命中"[:160],
           "modelName": "kb spider-live", "layout": "landscape", "unit": "task",
           "routes": ROUTES, "prompt": q}
    return cfg, events


def run(root: Path | None = None, *, spider_home: str | None = None,
        caller: str | None = None, max_sec: float = 0) -> None:
    """监听 traces → 直播。max_sec>0 到时退出(测试用), 0=常驻。"""
    home = find_spider_home(spider_home)
    root = Path(root) if root else kbtrace.kb_root()
    mcp = SpiderMcp(home)
    print(f"spider-live 已连接 {home}; 监听 {root / 'traces'} (Ctrl+C 退出)", flush=True)
    offsets: dict[Path, int] = {}
    active: dict[str, dict] = {}   # trace_id → {session, last_ts, pending_reads}
    t0 = time.monotonic()
    # 首见文件 birth 判定必须用 wall-clock(与 st_ctime 同钟系): 旧实现拿
    # monotonic 的 t0 与 epoch 秒的 st_ctime 比, 恒 False → 每次启动把所有历史
    # trace 从头回放(会话洪泛)。serve watcher 用 time.time() 是对的, 此处对齐。
    birth = time.time()
    try:
        while not max_sec or time.monotonic() - t0 < max_sec:
            d = kbtrace.traces_dir(root)
            if d.exists():
                for f in sorted(d.glob("*.jsonl")):
                    st = f.stat()
                    size = st.st_size
                    pos = offsets.get(f)
                    if pos is None:
                        # 首见文件: 启动后新文件从头播, 启动前已有的只记偏移不回灌
                        offsets[f] = 0 if st.st_ctime >= birth else size
                        continue
                    if size <= pos:
                        if size < pos:  # 文件被截断/重写: 重置
                            offsets[f] = 0
                        continue
                    # tail 语义(对齐 serve.TraceWatcher §30, 第十二轮走查): 只消费到
                    # 最后一个换行, 半行留在偏移外等下次轮询。旧实现 `offsets[f]=fh.tell()`
                    # (文本模式) 把偏移推进越过未写完字节 → 行补全后视为已消费, 该事件在
                    # 直播流里**永久漏播**(第十二轮同款缺陷, 当时只改了 serve 未同步这里)。
                    # 二进制读: st_size/偏移/截断检测同字节口径(\n 不在 UTF-8 多字节内)。
                    with f.open("rb") as fh:
                        fh.seek(pos)
                        chunk = fh.read()
                    cut = chunk.rfind(b"\n")
                    if cut < 0:
                        continue  # 至今无完整行(写入中), 偏移原地不动
                    offsets[f] = pos + cut + 1
                    for ln in chunk[:cut].decode("utf-8", "replace").splitlines():
                        try:
                            ev = json.loads(ln)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(ev, dict):
                            continue
                        # 与 serve watcher 同口径的解析期归一(returned=null 等脏
                        # 类型先归零再进映射, §26 同源); 再逐事件防护兜底:
                        # 单条坏事件绝不能掀翻整个直播进程。
                        kbtrace._coerce(ev, [], f.name)
                        try:
                            _dispatch(mcp, ev, active, caller)
                        except Exception:  # noqa: BLE001 - 观测桥故障不影响后续
                            continue
            now = time.monotonic()
            for tid in [t for t, a in active.items()
                        if now - a["last"] > COMPLETE_AFTER_SEC]:
                a = active.pop(tid)
                if a.get("has_hits"):
                    mcp.tool("spider_complete_session", {"sessionId": a["session"]})
            time.sleep(_POLL_SEC)
    except KeyboardInterrupt:
        pass
    finally:
        mcp.close()


def _dispatch(mcp: SpiderMcp, ev: dict, active: dict, caller: str | None) -> None:
    kind = ev.get("kind")
    if kind not in ("search", "get"):
        return
    if caller and ev.get("caller_repo") != caller:
        return
    tid = ev.get("trace_id")
    if not tid:
        return
    if kind == "search":
        cfg, events = event_to_updates(ev)
        sess = mcp.tool("spider_create_session", {"config": cfg})
        sid = sess.get("id") or sess.get("sessionId")
        if not sid:
            return
        print(f"[live] {sid} query={ev.get('query')!r} 命中 {len(events)} · {sess.get('previewUrl', '')}")
        if events:
            mcp.tool("spider_update_events", {"sessionId": sid, "events": events[:100]})
        else:  # 零命中也建会话: subtitle 已含死因, 直接定格
            mcp.tool("spider_complete_session", {"sessionId": sid})
        if events:
            active[tid] = {"session": sid, "last": time.monotonic(), "has_hits": True}
    elif tid in active:  # 迟到的 get → you 分支"已读消费"(id 与建会话时同样归一)
        a = active[tid]
        a["last"] = time.monotonic()
        if ev.get("ok"):
            mcp.tool("spider_update_events", {"sessionId": a["session"], "events": [
                {"id": spider_id(ev["id"]), "route": "you", "status": "completed"}]})
