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
import sys
import threading
import time
from pathlib import Path

from kb import trace as kbtrace

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
    returned = set(search.get("returned", []))
    layers = search.get("layers", [])
    proj_repo = layers[0]["repo"] if layers else None
    events, seen = [], set()
    for ly in layers:
        for m in ly.get("matched", []):
            if m["id"] not in returned or m["id"] in seen:
                continue
            seen.add(m["id"])
            events.append({"id": m["id"], "label": str(m.get("title") or m["id"])[:40],
                           "route": "code" if ly.get("repo") == proj_repo else "model",
                           "status": "running",
                           "detail": "hit: " + "+".join(m.get("hit_fields") or [])})
    for e in search.get("ext", []):  # 外接源命中 → ext 分支色(粉), label 带源名
        for eid in e.get("hits", []):
            if eid not in seen:
                seen.add(eid)
                events.append({"id": eid, "label": f"外接 {e.get('source')}: {eid}"[:40],
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
    try:
        while not max_sec or time.monotonic() - t0 < max_sec:
            d = kbtrace.traces_dir(root)
            if d.exists():
                for f in sorted(d.glob("*.jsonl")):
                    pos = offsets.get(f, f.stat().st_size if f.stat().st_ctime < t0 else 0)
                    if f.stat().st_size <= pos:
                        offsets[f] = f.stat().st_size
                        continue
                    with f.open("r", encoding="utf-8") as fh:
                        fh.seek(pos)
                        chunk = fh.read()
                        offsets[f] = fh.tell()
                    for ln in chunk.splitlines():
                        try:
                            ev = json.loads(ln)
                        except json.JSONDecodeError:
                            continue
                        _dispatch(mcp, ev, active, caller)
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
    elif tid in active:  # 迟到的 get → you 分支"已读消费"
        a = active[tid]
        a["last"] = time.monotonic()
        if ev.get("ok"):
            mcp.tool("spider_update_events", {"sessionId": a["session"], "events": [
                {"id": ev["id"], "route": "you", "status": "completed"}]})
