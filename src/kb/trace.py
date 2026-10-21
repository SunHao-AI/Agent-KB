"""检索埋点采集层 — 开关控制 / append-only JSONL / 失败静默。

数据层唯一事实源: <Agent-KB 仓根>/traces/YYYY-MM-DD.jsonl。
spec §4.2 红线: 事件只含元数据+摘要, 绝不含正文; 写失败静默放弃。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import uuid
from collections import OrderedDict
from pathlib import Path

SCHEMA = 2  # v2: search 事件+returned_chars, get 事件+chars(FR-1.2 估算节省 token 自包含)
_MARKER = ".kb-trace"
_ENV = "KB_TRACE"
_FALSY = ("", "0", "false", "False", "no")
_APPEND_LOCK = threading.Lock()  # 同进程多线程 append 互斥(Windows 并发写共享文件指针会丢/碎行)


def kb_root() -> Path:
    # src/kb/trace.py → parents[0]=kb, [1]=src, [2]=仓根(submodule 挂载点即仓根)
    return Path(__file__).resolve().parents[2]


def traces_dir(root: Path | None = None) -> Path:
    return (Path(root) if root else kb_root()) / "traces"


def trace_enabled(root: Path | None = None, cli_flag: bool | None = None) -> bool:
    """优先级: CLI 显式 > KB_TRACE 环境变量 > 仓根 .kb-trace 标记 > 默认关闭。"""
    if cli_flag is not None:
        return cli_flag
    env = os.environ.get(_ENV)
    if env is not None:
        return env.strip() not in _FALSY
    base = Path(root) if root else kb_root()
    return (base / _MARKER).exists()


def new_trace_id(ts: dt.datetime | None = None) -> str:
    ts = ts or dt.datetime.now()
    return f"t-{ts:%Y%m%d}-{uuid.uuid4().hex[:4]}"


def _today_file(root: Path | None) -> Path:
    return traces_dir(root) / f"{dt.date.today():%Y-%m-%d}.jsonl"


def append_event(event: dict, root: Path | None = None, *,
                 ingest: bool = True) -> None:
    """行级 append, 新文件补 meta 行。任何 OSError 静默放弃。

    落盘即事实源成立; 之后若配置了 ingest 目标(FR-2.5 团队态直播通道),
    尽力异步 POST 一份 —— 失败静默、不重试第二跳、绝不反向影响检索。
    serve 端接收 ingest 后落盘时必须传 ingest=False, 防中继回环。
    """
    try:
        f = _today_file(root)
        f.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(event, ensure_ascii=False)
        with _APPEND_LOCK:  # 锁内一次写完多行, 保证行完整性
            head = [] if f.exists() else [json.dumps({"kind": "meta", "schema": SCHEMA},
                                                     ensure_ascii=False)]
            with f.open("a", encoding="utf-8") as fh:
                fh.write("".join(ln + "\n" for ln in [*head, line]))
    except OSError:
        return
    if ingest:
        _post_ingest(event)


def _post_ingest(event: dict) -> None:
    try:
        from urllib.request import Request, urlopen
        from kb.userconf import ingest_target
        url, token = ingest_target()
        if not url:
            return
        req = Request(url.rstrip("/") + "/api/ingest",
                      data=json.dumps(event, ensure_ascii=False).encode("utf-8"),
                      headers={"Content-Type": "application/json",
                               **({"Authorization": f"Bearer {token}"} if token else {})},
                      method="POST")
        urlopen(req, timeout=1.0).close()  # 失败由外层 except 静默吞掉
    except Exception:
        return


_parse_cache: "OrderedDict[Path, tuple[tuple, list, list, list]]" = OrderedDict()  # 序 = LRU
_cache_lock = threading.Lock()  # ThreadingHTTPServer 多线程读路径共用缓存
_CACHE_CAP = 32  # 解析缓存文件数上限; 实测 28 日文件/2.15万事件常驻 ≈85MB, 高量团队态约 100MB 封顶


def _parse_file(f: Path) -> tuple[list, list, list]:
    """单文件解析(mtime_ns+size 签名缓存, LRU)。append-only 语义下签名不变=内容不变;
    缓存出的事件 dict 按只读约定共享(全消费侧无原地改写), 勿新增写入方。
    文件 IO 在锁外(避免并发读互相串行), 锁只护缓存表; 冷路径重复解析同文件仅浪费一次。"""
    st = f.stat()
    sig = (st.st_mtime_ns, st.st_size)
    with _cache_lock:
        hit = _parse_cache.get(f)
        if hit and hit[0] == sig:
            _parse_cache.move_to_end(f)
            return hit[1], hit[2], hit[3]
    searches: list[dict] = []
    gets: list[dict] = []
    warns: list[str] = []
    lines = [ln for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if not lines:
        warns.append(f"{f.name}: 空文件, 跳过")
    else:
        try:
            meta = json.loads(lines[0])
        except json.JSONDecodeError:
            meta = {}
        if meta.get("kind") != "meta":
            warns.append(f"{f.name}: 缺 meta 首行, 跳过")
        elif int(meta.get("schema", 0)) > SCHEMA:
            warns.append(f"{f.name}: schema={meta.get('schema')} "
                         f"高于本地 {SCHEMA}, 跳过")
        else:
            for ln in lines[1:]:
                try:
                    ev = json.loads(ln)
                except json.JSONDecodeError:
                    warns.append(f"{f.name}: bad line 跳过")
                    continue
                if ev.get("kind") == "search":
                    searches.append(ev)
                elif ev.get("kind") == "get":
                    gets.append(ev)
    with _cache_lock:
        _parse_cache[f] = (sig, searches, gets, warns)
        _parse_cache.move_to_end(f)
        while len(_parse_cache) > _CACHE_CAP:  # LRU 逐出(按日分片, 最久未用先出)
            _parse_cache.popitem(last=False)
    return searches, gets, warns


def _iter_raw(root: Path) -> tuple[list[dict], list[dict], list[str]]:
    searches: list[dict] = []
    gets: list[dict] = []
    warns: list[str] = []
    d = traces_dir(root)
    if not d.exists():
        return searches, gets, warns
    for f in sorted(d.glob("*.jsonl")):
        s, g, w = _parse_file(f)
        searches.extend(s)
        gets.extend(g)
        warns.extend(w)
    return searches, gets, warns


def _newest_first(events: list[dict]) -> list[dict]:
    return sorted(events, key=lambda e: str(e.get("ts", "")), reverse=True)


def read_traces(root: Path | None = None, *, caller: str | None = None,
                since: str | None = None, zero_hit: bool = False,
                limit: int | None = None) -> tuple[list[dict], list[dict], list[str]]:
    base = Path(root) if root else kb_root()
    searches, gets, warns = _iter_raw(base)
    if caller:
        searches = [s for s in searches if s.get("caller_repo") == caller]
        gets = [g for g in gets if g.get("caller_repo") == caller]
    if since:
        searches = [s for s in searches if str(s.get("ts", ""))[:10] >= since]
    if zero_hit:
        searches = [s for s in searches if not s.get("returned")]
    searches, gets = _newest_first(searches), _newest_first(gets)
    if limit is not None:
        searches = searches[:limit]
    return searches, gets, warns


def find_trace(trace_id: str, root: Path | None = None) -> dict | None:
    searches, _, _ = _iter_raw(Path(root) if root else kb_root())
    return next((s for s in searches if s.get("trace_id") == trace_id), None)


def latest_search_id(caller_repo: str, root: Path | None = None) -> str | None:
    searches, _, _ = _iter_raw(Path(root) if root else kb_root())
    hits = _newest_first([s for s in searches if s.get("caller_repo") == caller_repo])
    return hits[0].get("trace_id") if hits else None


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def build_search_event(*, trace_id: str, source: str, caller_repo: str,
                       query: str | None, filters: dict, limit: int,
                       reports: list[dict], returned: list[str],
                       duration_ms: int, returned_chars: int | None = None,
                       ts: str | None = None) -> dict:
    """逐层报告 → search 事件(字段序即 spec §4.4 schema)。只取元数据, 不带正文。

    returned_chars: 本次返回给调用方的序列化字符数(FR-1.2 知识库自身开销/节省
    token 估算用); 调用方未传则省略字段, 聚合侧按"未知"跳过。
    """
    ev = {
        "kind": "search", "trace_id": trace_id, "ts": ts or _now(), "source": source,
        "caller_repo": caller_repo, "query": query,
        "filters": {k: filters.get(k) for k in
                    ("type", "domain", "tag", "scope", "status", "confidence")},
        "limit": limit, "duration_ms": duration_ms,
        "layers": [{"repo": r["repo"], "scanned": r["scanned"],
                    "rejected": r["rejected"], "matched": r["matched"],
                    "taken": r["taken"], "truncated_at_limit": r["truncated_at_limit"]}
                   for r in reports],
        "returned": list(returned),
    }
    if returned_chars is not None:
        ev["returned_chars"] = int(returned_chars)
    return ev


def build_get_event(*, trace_id: str | None, source: str, caller_repo: str, id: str,
                    layer: str | None, ok: bool, chars: int | None = None,
                    ts: str | None = None) -> dict:
    """chars: 本次读到的全文字符数(FR-1.2 消费口径), ok=False 时无意义省略。"""
    ev = {"kind": "get", "trace_id": trace_id, "ts": ts or _now(), "source": source,
          "caller_repo": caller_repo, "id": id, "layer": layer, "ok": ok}
    if chars is not None:
        ev["chars"] = int(chars)
    return ev
