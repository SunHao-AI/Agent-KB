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


def _coerce(ev: dict, warns: list[str], src: str) -> None:
    """解析期就地归一化(对象此刻尚未入缓存, 私有可写; 入缓存后一律只读):
    trace 文件由各客户端/手工写入, 属不可信输入; stats 用 len(returned)/int(chars)
    直接消费, 脏类型会让 API 线程抛 TypeError → 连接被重置(§26 实测: returned=null
    使 stats/feed/callers 三端点全挂)。原则: 只归一"会让算术崩"的类型,
    语义脏值(负耗时/怪 ts)如实呈现不篡改。"""
    ret = ev.get("returned")
    if "returned" in ev and ret is None:
        ev["returned"] = []                      # 显式 null 视为零命中(字段缺失本已安全)
    elif ret is not None and not isinstance(ret, list):
        warns.append(f"{src}: returned 非列表({type(ret).__name__}), 按零命中处理")
        ev["returned"] = []
    # §50: 列表字段归一当初只做了 returned, `layers: null` 同样炸——stats 的
    # 消费方一半写 `.get(k, [])`(默认值对"键存在但为 null"不生效, 与 §47 的
    # .get 陷阱同源), 一半写 `or []`(安全)。消费方逐点补防不如解析期一次
    # 归零: 同一事实源进缓存前所有列表字段口径统一, 新增消费方不再踩。
    for k in ("layers", "ext", "suggest", "read"):
        v = ev.get(k)
        if v is None:
            if k in ev:
                del ev[k]                        # 显式 null → 视作缺失(下游默认值生效)
        elif not isinstance(v, list):
            warns.append(f"{src}: {k} 非列表({type(v).__name__}), 按缺失处理")
            del ev[k]
    # §77: §50 的列表归一只到"是不是 list"为止, 元素级裸奔同族引爆——手工/异构
    # 客户端写 layers:["x"] 通过归一后, stats 的 by_source/callers/feed_events/
    # top_consumed 四个消费方全部 `ly.get(...)` AttributeError(探针实锤, serve
    # stats/callers/feed 三端点 500)。"消费方逐点补防不如解析期一次归零"的
    # 原则下钻一层: 结构字段(layers/ext)的元素必须是 dict, 非 dict 元素剔除;
    # layers 元素内的 matched 同规则(须为 list 且元素为 dict)。
    # 就地过滤[:]——缓存共享的 dict 引用不变, 重复净化幂等。
    def _only_dicts(lst: list, what: str) -> list:
        keep = [x for x in lst if isinstance(x, dict)]
        if len(keep) != len(lst):
            warns.append(f"{src}: {what} 含非对象元素, 已剔除"
                         f"({len(lst) - len(keep)} 个)")
        return keep

    for k in ("layers", "ext"):
        v = ev.get(k)
        if isinstance(v, list):
            keep = _only_dicts(v, k)
            if len(keep) != len(v):
                ev[k] = keep                     # 剔的是顶层列表槽位, 可换引用
    for ly in ev.get("layers") or []:
        if isinstance(ly, dict):
            m = ly.get("matched")
            if m is not None and not isinstance(m, list):
                del ly["matched"]                # 标量 matched: 消费方 .get([], []) 兜底
            elif isinstance(m, list):
                keep = _only_dicts(m, "layers.matched")
                if len(keep) != len(m):
                    m[:] = keep                  # 嵌套列表就地过滤, 不动共享引用
    # §52: 身份字段非字符串同族——caller_repo/ts 会进 by_caller 键与 ts_key 比较,
    # ingest 口已拒收(serve §52), 但手工写入/异构客户端的存量文件仍可能带 dict/
    # list; 读侧一并净化(删键+warn), 坏事件降级为"项目未知"而非打崩聚合。
    for k in ("trace_id", "id", "caller_repo", "layer", "source", "ts"):
        v = ev.get(k)
        if v is not None and not isinstance(v, str):
            warns.append(f"{src}: {k} 非字符串({type(v).__name__}), 按缺失处理")
            del ev[k]
    # §55: query 是检索词而非身份, 数值查询(agent 查"123"被 JSON 化成 123)
    # 标量化保留语义; 容器(list 不可哈希、dict)删键——消费方 top_queries 拿它
    # 做 Counter 键、zero_hit_board 调 .strip(), 第三十七轮实测双双崩。
    q = ev.get("query")
    if q is not None and not isinstance(q, str):
        if isinstance(q, (int, float, bool)):
            ev["query"] = str(q)
            warns.append(f"{src}: query 非字符串({type(q).__name__}), 已转字符串")
        else:
            del ev["query"]
            warns.append(f"{src}: query 为容器({type(q).__name__}), 按缺失处理")
    for k in ("chars", "returned_chars"):
        v = ev.get(k)
        if v is not None and not isinstance(v, (int, float)):
            warns.append(f"{src}: {k} 非数值({type(v).__name__}), 该次不计入")
            ev[k] = None                         # 下游 `is None` 分支已正确跳过


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
        # meta 行同属不可信输入(§26 净化了事件行却漏了 meta 行, §47): 非对象行
        # (JSON 数组/标量)让 .get 抛 AttributeError、schema 非数值让 int() 抛
        # ValueError——_parse_file 爆炸沿 read_traces 上炸 stats/feed/callers
        # 三端点全挂, 与事件行崩的爆炸半径完全相同。
        skip = False
        if not isinstance(meta, dict) or meta.get("kind") != "meta":
            warns.append(f"{f.name}: 缺 meta 首行, 跳过")
            skip = True
        else:
            try:
                schema = int(meta.get("schema", 0))
            except (TypeError, ValueError):
                schema = SCHEMA  # 读不懂的 schema 标记: 按兼容处理, 事件仍如实呈现
                warns.append(f"{f.name}: schema={meta.get('schema')!r} 非数值, "
                             f"按本地 {SCHEMA} 兼容读取")
            if schema > SCHEMA:
                warns.append(f"{f.name}: schema={meta.get('schema')} "
                             f"高于本地 {SCHEMA}, 跳过")
                skip = True
        if not skip:
            for ln in lines[1:]:
                try:
                    ev = json.loads(ln)
                except json.JSONDecodeError:
                    warns.append(f"{f.name}: bad line 跳过")
                    continue
                if not isinstance(ev, dict):
                    warns.append(f"{f.name}: 非对象事件跳过")
                    continue
                _coerce(ev, warns, f.name)
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


def ts_key(ts) -> tuple:
    """时刻比较键: 带 tz 偏移的 ISO 串归一到 UTC 秒, 显示仍用原串(面板以写入机钟点为准)。

    字符串比较**只在全体同偏移时**才等于时刻序。团队态联邦成员跨时区上报
    (ts 各带本机偏移, 见 `_now`), 上海 `09:00+08:00` 与纽约 `08:00-05:00` 字符串序判
    上海晚, 实际纽约晚 12h——排序/最近活跃/消化方向都会失真。
    解析失败退回 `(0, 原文, 0)`(同格式自洽, 老数据不炸); 返回元组而非裸 float 是为
    保证任意两个键可比。
    """
    s = str(ts or "")
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        return (0, s, 0.0)
    if d.tzinfo is None:  # 无偏移按写入机时区理解(与 _now 的 astimezone 一致)
        d = d.replace(tzinfo=dt.datetime.now().astimezone().tzinfo)
    return (1, "", d.astimezone(dt.timezone.utc).timestamp())


def _newest_first(events: list[dict]) -> list[dict]:
    return sorted(events, key=lambda e: ts_key(e.get("ts")), reverse=True)


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
        # limit 契约(§58, sources/layers 同族): Python 切片 `[:-2]` 是"去掉尾部
        # 两个"而非"取前 -2 个"——`kb trace list --limit -2` 曾返回全量减 2 条,
        # "要最少给最多"的翻转语义。≤0 一律零名额(空), None 才是"不限"。
        searches = searches[:limit] if limit > 0 else []
    return searches, gets, warns


def find_trace(trace_id: str, root: Path | None = None) -> dict | None:
    searches, _, _ = _iter_raw(Path(root) if root else kb_root())
    return next((s for s in searches if s.get("trace_id") == trace_id), None)


def latest_search_id(caller_repo: str, root: Path | None = None,
                     entry_id: str | None = None) -> str | None:
    """get 事件尽力关联到某次 search 的 trace_id(spec §4.4)。

    传入 entry_id 时优先精确匹配: 返回过该条目的最近一次 search(kb_get(id) 的 id
    几乎必然来自某次 search 的 returned)。旧实现只取"最近一次 search", 多轮检索
    后读早轮返回的条目会挂错 trace, 消费判定(_consumed_ids 要求同 trace 返回过该
    id)判"未消费"——第二十二轮走查实测该漏计使头条 consume_rate 系统性偏低。
    匹配不到(手动 get / 关联真断裂)回退纯最近一次, 保持 spec"尽力关联, 关联不上
    为 null"的底线语义。
    """
    searches, _, _ = _iter_raw(Path(root) if root else kb_root())
    hits = _newest_first([s for s in searches if s.get("caller_repo") == caller_repo])
    if entry_id:
        for s in hits:
            if entry_id in (s.get("returned") or []):
                return s.get("trace_id")
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
    if not returned:
        # 零命中事件透传 suggest(FR-3.2): 周报"已消化"要判"按 suggest 改写后命中",
        # 建议词只能挂在失败事件上(第十六轮前的旧实现挂在命中事件侧, 恒 None 死分支)。
        sug = next((r.get("suggest") for r in reports if r.get("suggest")), None)
        if sug:
            ev["suggest"] = list(sug)
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
