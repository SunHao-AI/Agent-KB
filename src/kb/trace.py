"""检索埋点采集层 — 开关控制 / append-only JSONL / 失败静默。

数据层唯一事实源: <Agent-KB 仓根>/traces/YYYY-MM-DD.jsonl。
spec §4.2 红线: 事件只含元数据+摘要, 绝不含正文; 写失败静默放弃。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
import uuid
from collections import OrderedDict
from pathlib import Path

SCHEMA = 2  # v2: search 事件+returned_chars, get 事件+chars(FR-1.2 估算节省 token 自包含)

# 三级披露的机器面口径(2026-11-13 起写进事件, 旧事件无这两个字段, 聚合按 kind 兜底):
# L1 = AGENTS.md 由宿主(IDE/agent 框架)装进系统提示, kb 进程不参与读取 —— 没有事件,
#      恒不可观测, 不能用 0 冒充"没人读";
# L2 = 检索面, 机器载体是 kb/index.jsonl(kb/INDEX.md 只是人读投影), 每次 search 一条;
# L3 = 条目正文 markdown, 每次 get 一条。
# 显式声明层级后, "只看元数据/继续读全文"可直接判定, 不必再从 returned_chars 反推。
LEVEL_SEARCH, LEVEL_GET = 2, 3
SURFACE_SEARCH = "index.jsonl"
SURFACE_GET = "entry.md"
_MARKER = ".kb-trace"
_ENV = "KB_TRACE"
_FALSY = ("", "0", "false", "False", "no")
_APPEND_LOCK = threading.Lock()  # 同进程多线程 append 互斥(Windows 并发写共享文件指针会丢/碎行)
_LOCK_SUFFIX = ".lock"           # 跨进程锁 sidecar: 不带 .jsonl, 避开读侧 glob("*.jsonl")
_LOCK_TIMEOUT = 3.0              # 单条埋点的持锁上限; 超时宁可丢事件也不阻塞检索链路
_LOCK_POLL = 0.02

try:
    import msvcrt as _msvcrt
except ImportError:
    _msvcrt = None
if _msvcrt is None:
    import fcntl as _fcntl
else:
    _fcntl = None


def _try_lock(fh) -> bool:
    """非阻塞独占锁: 拿到 True, 被他人持有 False。"""
    try:
        if _msvcrt is not None:
            fh.seek(0)
            _msvcrt.locking(fh.fileno(), _msvcrt.LK_NBLCK, 1)
        else:
            _fcntl.flock(fh.fileno(), _fcntl.LOCK_EX | _fcntl.LOCK_NB)
        return True
    except OSError:
        return False


def _unlock(fh) -> None:
    try:
        if _msvcrt is not None:
            fh.seek(0)
            _msvcrt.locking(fh.fileno(), _msvcrt.LK_UNLCK, 1)
        else:
            _fcntl.flock(fh.fileno(), _fcntl.LOCK_UN)
    except OSError:
        pass


def _append_locked(target: Path, lines: list[str], lock_path: Path | None = None) -> bool:
    """进程内锁 + OS 文件锁双保险下追加整行; 取锁超时返回 False(调用方静默丢事件)。

    为什么必须上 OS 锁(kb-20261021-6223 的遗留边界): Windows CRT 的 `O_APPEND`
    只在 open 时定位一次 EOF, 之后各句柄按自己的指针推进 —— 同进程多线程已由
    `_APPEND_LOCK` 串行, 但 serve(ThreadingHTTPServer) / CLI / MCP 是**多进程**同写
    当日文件, 线程锁跨不过进程, 并发下互相覆盖并留下半行碎片(线上实测:
    traces/2026-11-06 与 2026-11-11 各残留 1 条孤儿片段)。
    """
    deadline = time.monotonic() + _LOCK_TIMEOUT
    with _APPEND_LOCK:
        sidecar = None
        if lock_path is not None:
            try:
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                sidecar = lock_path.open("a+b")
            except OSError:
                sidecar = None
        try:
            if sidecar is not None:
                while not _try_lock(sidecar):
                    if time.monotonic() >= deadline:
                        return False
                    time.sleep(_LOCK_POLL)
            head = [] if target.exists() else [
                json.dumps({"kind": "meta", "schema": SCHEMA}, ensure_ascii=False)]
            with target.open("a", encoding="utf-8", newline="\n") as fh:
                fh.write("".join(ln + "\n" for ln in [*head, *lines]))
            return True
        finally:
            if sidecar is not None:
                _unlock(sidecar)
                sidecar.close()


def kb_root() -> Path:
    # src/kb/trace.py → parents[0]=kb, [1]=src, [2]=仓根(submodule 挂载点即仓根)
    return Path(__file__).resolve().parents[2]


def traces_dir(root: Path | None = None) -> Path:
    return (Path(root) if root else kb_root()) / "traces"


def _in_pytest_session() -> bool:
    """当前是否处于 pytest 测试执行期(该变量只在测试执行期存在, 真实进程恒假)。"""
    return bool(os.environ.get("PYTEST_CURRENT_TEST"))


def _pytest_tmp_root() -> str:
    """pytest 临时根(tmp_path 的父目录); 未导出时返回 ""。"""
    return os.environ.get("PYTEST_DEBUG_TEMPROOT", "").replace("\\", "/").rstrip("/")


def _under(path: Path, base: str) -> bool:
    s = str(path).replace("\\", "/")
    if base and (s == base or s.startswith(base + "/")):
        return True
    return "pytest-of-" in s          # basetemp 固定命名, 兜住 DEBUG_TEMPROOT 缺省


def trace_enabled(root: Path | None = None, cli_flag: bool | None = None) -> bool:
    """优先级: 测试隔离 > CLI 显式 > KB_TRACE 环境变量 > 仓根 .kb-trace 标记 > 默认关闭。

    测试隔离红线: pytest 会话内, 埋点只准写落在 pytest 临时目录下的根。
    仓根 `.kb-trace` 标记让埋点默认常开, 而 `append_event(ev)` 不带 root 时按
    **真实仓根**落盘 —— 未 monkeypatch `kb_root` 的用例(如 test_cli 的检索用例)
    于是把合成语料写进了 git 里的观测账本。2026-11-02 实测: traces/ 里 105 条
    「vite」零命中全部来自 pytest(35 条 caller=`test_cli_missing_repo_path_err*`
    /`scanned:0`, 70 条 caller=`docs`/`layers:[]`), 命中率、零命中榜、消化率三个
    头号指标被同一污染源打歪。

    判据是"落盘目标在不在临时目录内", 不是"是不是测试进程": 埋点自身的测试会
    monkeypatch `kb_root` 到 tmp_path, 那是必须保留的覆盖面, 照常按下面的优先级
    走; 真实账本(仓内 traces/)在临时目录之外, 测试进程永远写不到。
    """
    if _in_pytest_session():
        target = Path(root) if root else kb_root()
        if not _under(target, _pytest_tmp_root()):
            return False             # 测试写真实账本: 一律拒绝
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

    写时标记 `synthetic=true`: 测试进程把事件写到 pytest 沙箱**之外**(真实账本)
    时打标, 与 caller 名/扫描规模等启发式判据解耦。沙箱内的写入不打标——那是
    用例自建的合法夹具目录, 永远不会被真实面板读到, 打标反而会把"用 append_event
    造数据"的聚合测试整批剔空。只加字段不改 `source`(cli/mcp 分渠道语义不变)。
    """
    ev = event
    if "synthetic" not in ev and _in_pytest_session():
        target = Path(root) if root else kb_root()
        if not _under(target, _pytest_tmp_root()):
            ev = {**ev, "synthetic": True}
    try:
        f = _today_file(root)
        f.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(ev, ensure_ascii=False)
        _append_locked(f, [line], lock_path=f.with_suffix(_LOCK_SUFFIX))
    except OSError:
        return
    if ingest:
        _post_ingest(ev)


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
    for k in ("trace_id", "id", "caller_repo", "layer", "source", "ts", "surface"):
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
    # level 是三级披露的层级声明(1/2/3), 只认这三个整数; 脏值删键让聚合按 kind 兜底,
    # 不把 True/浮点/"2" 之类的脏值带进层级统计。旧事件本就没有该键, 属正常缺失。
    # NaN/Infinity 是 Python json 允许的字面量(int() 会抛), 一并归到"非法"分支。
    lv = ev.get("level")
    if lv is not None:
        bad = isinstance(lv, bool) or not isinstance(lv, (int, float))
        if not bad:
            try:
                bad = int(lv) not in (1, 2, 3)
            except (ValueError, OverflowError):
                bad = True
        if bad:
            warns.append(f"{src}: level 非法({lv!r}), 按 kind 兜底层级")
            del ev["level"]
        elif not isinstance(lv, int):
            ev["level"] = int(lv)
    # synthetic 是写时布尔标记(见 append_event), 判据只认 True/False 本身:
    # 手工写入的 "yes"/1 按标量真值归一, 容器删键(否则下游 `is True` 静默失效)。
    sy = ev.get("synthetic")
    if sy is not None and not isinstance(sy, bool):
        if isinstance(sy, (int, float, str)):
            ev["synthetic"] = bool(sy) and str(sy).strip().lower() not in _FALSY
        else:
            warns.append(f"{src}: synthetic 为容器({type(sy).__name__}), 按缺失处理")
            del ev["synthetic"]


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
    # errors="replace": 账本 append-only(kb-2026-11-02-caller), 写入侧一旦落进非 UTF-8
    # 字节就永久留在历史里, 严格解码会让整个文件读不出来 → stats/feed/report 全挂。
    # 替换后坏行由下面的 bad line 分支跳过并记 warn, 与 §26/§47 的行级容错口径一致。
    lines = [ln for ln in f.read_text(encoding="utf-8", errors="replace").splitlines()
             if ln.strip()]
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


QUARANTINE_FILE = "synthetic-ids.json"
# 清单键的白名单: 未知键(常见笔误 id/until_ts)必须报 warn 而不是静默忽略——
# 写错一个键 = 该规则永不命中 = 隔离形同虚设, 而数字看起来"很干净"。
_QUARANTINE_KEYS = ("caller_repo", "kinds", "ids", "max_scanned",
                    "since", "until", "why", "evidence")
_QUARANTINE_MATCHERS = ("caller_repo", "kinds", "ids", "max_scanned")


def load_quarantine(root: Path | None = None) -> tuple[list[dict], list[str]]:
    """读 `traces/synthetic-ids.json`: 历史测试夹具事件的**显式登记**清单。

    为什么需要它(启发式的盲区): `stats.synthetic_callers` 按 caller 名与扫描
    规模判合成, 只能整 caller 剔。`caller_repo=docs` 既有 332 条真实检索(扫 300+
    条), 也有 178 条 conftest 夹具检索(扫 1-2 条)——同一 caller 混着真实与合成,
    整 caller 剔会连真实数据一起丢, 不剔则夹具照旧刷榜(实测 177 条 get 全落在
    `kb-20261014-e1e1`/`kb-20261014-0000`/`source://demo/d1` 三个夹具 id)。

    原则与 caller 剔噪一致: **改口径不抹事件**。账本是 append-only 事实源, 这里
    只在读侧登记"哪些历史事件属于测试语料", 事件本身与 raw=1 逃生门都保留。

    规则语义: 单条规则内所有已给条件 **AND**; 至少给一个匹配条件(否则会吞全库);
    日期为 `[since, until]` 闭区间、按 ts 的日粒度。返回 (规则列表, 告警列表)。
    """
    base = Path(root) if root else kb_root()
    path = traces_dir(base) / QUARANTINE_FILE
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], []
    except OSError as exc:
        return [], [f"{QUARANTINE_FILE}: 读取失败({exc.__class__.__name__}), 隔离未生效"]
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError:
        return [], [f"{QUARANTINE_FILE}: JSON 解析失败, 隔离未生效"]
    if not isinstance(doc, dict) or not isinstance(doc.get("rules"), list):
        return [], [f"{QUARANTINE_FILE}: 顶层须为 {{\"rules\": [...]}}, 隔离未生效"]
    rules: list[dict] = []
    warns: list[str] = []
    for i, r in enumerate(doc["rules"]):
        tag = f"{QUARANTINE_FILE}#rules[{i}]"
        if not isinstance(r, dict):
            warns.append(f"{tag}: 非对象, 跳过")
            continue
        unknown = [k for k in r if k not in _QUARANTINE_KEYS]
        if unknown:
            warns.append(f"{tag}: 未知键 {unknown}, 已忽略")
        rule = {k: r[k] for k in _QUARANTINE_KEYS if k in r}
        if not any(k in rule for k in _QUARANTINE_MATCHERS):
            warns.append(f"{tag}: 缺匹配条件({'/'.join(_QUARANTINE_MATCHERS)}), 跳过"
                         "(无条件的规则会吞掉全库)")
            continue
        if not rule.get("why"):
            warns.append(f"{tag}: 缺 why(隔离理由), 跳过")
            continue
        rules.append(rule)
    return rules, warns


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
    level/surface: 显式声明这次读的是三级披露的哪一层(见模块常量), 让"只看
    元数据"可判定; 旧事件无此字段时聚合按 kind 兜底(search→L2)。
    """
    ev = {
        "kind": "search", "trace_id": trace_id, "ts": ts or _now(), "source": source,
        "level": LEVEL_SEARCH, "surface": SURFACE_SEARCH,
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
    """chars: 本次读到的全文字符数(FR-1.2 消费口径), ok=False 时无意义省略。
    level/surface: 显式声明这是 L3(条目正文)读取; 旧事件无此字段时按 kind 兜底。"""
    ev = {"kind": "get", "trace_id": trace_id, "ts": ts or _now(), "source": source,
          "level": LEVEL_GET, "surface": SURFACE_GET,
          "caller_repo": caller_repo, "id": id, "layer": layer, "ok": ok}
    if chars is not None:
        ev["chars"] = int(chars)
    return ev
