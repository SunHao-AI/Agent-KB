"""观测聚合层 — PRD FR-1.2 指标口径的唯一实现。

kb serve 的 REST/SSE 全部经本模块出数; 客户端与 CLI 只做展示不另算口径。
输入是 trace 事件原文(read_traces 产物), 纯函数无 IO, 便于单测。

口径(与 PRD §FR-1.2 一一对应):
- 命中率     : returned 非空的 search 事件数 / search 事件数(逐次计, 不按 query 去重)
- 消费率     : 被返回且被同 trace_id 关联 kb_get(ok) 读过的条目数 / 被返回条目总数
- 估算节省   : Σ(被消费 get 的 chars) − Σ(消费它的 search 中该条目摘要级 returned_chars
              按比例摊额); search 事件缺 returned_chars 或 get 缺 chars → 该次跳过。
              ⚠ 估算指标, 展示必须带"估算"标识, 禁止包装成精确承诺。
- 自身开销   : Σ returned_chars(全部 search 事件, 缺失记 0 并计入 unknown_count)
- 层级读取   : L1=AGENTS.md 由宿主装载进系统提示, kb 进程不参与 → 无事件、恒不可观测
              (如实出 `observable: false`, 不用 0 冒充"没人读"); L2=每次 search
              (机器面 kb/index.jsonl, INDEX.md 只是人读投影); L3=每次 get(条目正文)。
              事件自 2026-11-13 起带显式 level/surface, 旧事件按 kind 兜底归类。
- 只看元数据 : 有返回、但同 trace_id 未读任何返回条目的检索(meta_only)的
              次数/字符数; meta_only + meta_to_full = 有返回的检索数, 两者字符
              之和不超过 overhead_chars(差额是零命中事件), 可与既有 KPI 对账。
- 零命中榜   : returned 为空的 search 按 query 频次倒序; 同 caller 后续同 query 或
              suggest 词命中 → 标 digested(已消化)。
"""
from __future__ import annotations

import datetime as dt
import re

# _ts_key 单一事源在 trace.ts_key(第十九轮 §37 上移); 曾在此留有一份逐行相同
# 的本地 def 遮蔽了导入(ruff F811 抓获, 第二十九轮清理)——两份"同源"实现
# 迟早漂移, 删除副本让导入真正生效。
from .trace import SURFACE_GET, SURFACE_SEARCH
from .trace import ts_key as _ts_key

# 消费侧埋点起点: CLI `kb show` 从这天起才写 get 事件(此前只有 MCP `kb_get`)。
# 早于该日的窗口里"读全文"是不可见的 → 消费率只能是**下界**, 不是"没人读"。
# 面板据此把纯历史窗口显示为"未采集", 部分跨越时标"含 N 次埋点前检索"。
CONSUME_TRACKING_SINCE = "2026-11-13"
# 层级/surface 显式字段的埋点起点(与消费埋点同日): 更早的事件没有 level/surface,
# 聚合按 kind 兜底归类; 面板据此说明"显式层级字段 N/M"而不是假装全都有。
LAYER_TRACKING_SINCE = "2026-11-13"


def _within(ev: dict, since: str | None, until: str | None) -> bool:
    day = str(ev.get("ts", ""))[:10]
    return not ((since and day < since) or (until and day > until))


def not_executed(ev: dict) -> bool:
    """该 search 事件是否"检索根本没扫过库"—— 不计入命中率/零命中榜的分子分母。

    2026-11-02 实测的假信号有两类形态, 共同点是没有任何条目被真正扫描过:
    - `layers` 缺失/为空: MCP 的 limit<=0 分支(直接返回提示, 不扫库)与客户端
      异常路径上报;
    - 所有层 `scanned: 0`: 空仓/合成语料(历史 traces 里 105 条「vite」零命中
      全是这种, 同期「vite」真实命中 231 次, 榜首完全是噪声)。

    这类事件不是"库里没有答案", 而是"没问过库"。把它们算进零命中榜会直接指错
    方向——FR-3.5 的补库回路会照着一个已有 231 次命中的词去补条目。命中态事件
    (returned 非空)必然扫过库, 判定上优先放行, 避免把 schema 老数据误剔。
    """
    if ev.get("returned"):
        return False
    layers = ev.get("layers") or []
    if not layers:
        return True
    return not any(int(ly.get("scanned") or 0) for ly in layers)


def effective(searches: list[dict]) -> list[dict]:
    """真正执行过的 search(见 not_executed); 榜单/KPI 的统一入户口。"""
    return [s for s in searches if not not_executed(s)]


# ---- 合成语料(测试污染)剔噪 --------------------------------------------------

# pytest 用例名派生的 tmp_path 目录名: test_xxx 被 pytest 截断到 30 字符再拼序号
# (实测 `test_cli_index_then_search_jso0` / `test_cli_missing_repo_path_err0`)。
_TEST_CALLER = re.compile(r"^test_.+_\d\d?$")
# 合成夹具的层规模上限: conftest.make_entry 建的仓只有 1-2 条条目。
_SYNTH_MAX_SCAN = 2


def synthetic_callers(searches: list[dict]) -> set[str]:
    """判定哪些 caller 的检索事件**全部**来自测试合成语料(逐条判会误伤真实仓)。

    2026-11-02 取证: traces/ 里 1311 条事件中 330 条(25%)来自 pytest——写侧红线
    (trace.trace_enabled: 测试进程只准写 pytest 临时目录)是本轮才补上的, 而
    traces/ 已按每日定时任务提交进 git, 历史污染无法靠"以后不写"清掉。留着的代价
    不是"数字略脏": 高返回零消费榜两条并列榜首(各 61 次)是 conftest 合成夹具
    `kb-20261012-aaaa`/`kb-20261014-f2f2`, 照它去"净化摘要"是纯白做功。

    判据两条, 任一命中即整 caller 剔(不做逐条, 合成 caller 里没有真实事件混着):
    1. caller 名是 pytest tmp_path 形态(铁证, 真实仓名不会长这样);
    2. 该 caller **所有** search 的 max(layers.scanned) ≤ 2 —— 合成夹具只有 1-2 条
       条目, 真实仓(本仓 202 / 业务仓 100~220 条)不可能长期停在 2 以下。
       **故意用"全部"而非"存在"**: 刚接入、只有 1-2 条条目的真实仓一旦出现过一次
       大扫描(=库里长过), 就永不被误剔。

    已知误判面(可接受, 面板如实标注剔了多少): 真实仓在只有 ≤2 条条目期间的所有
    检索会被当合成剔掉——那段数据本也无观测价值(样本 <3 时 cold_start 已拒绝出比率)。
    `/api/stats?raw=1` 可回到含噪声原始口径自查。
    """
    seen: dict[str, int] = {}
    out: set[str] = set()
    for s in searches:
        c = s.get("caller_repo")
        if not isinstance(c, str) or not c:
            continue
        if _TEST_CALLER.match(c):
            out.add(c)
            continue
        ls = s.get("layers") or []
        mx = max((int(ly.get("scanned") or 0) for ly in ls if isinstance(ly, dict)),
                 default=0)
        seen[c] = max(seen.get(c, 0), mx)
    out |= {c for c, mx in seen.items() if mx <= _SYNTH_MAX_SCAN}
    return out


def denoise(searches: list[dict], gets: list[dict]) -> tuple[list, list, int, set]:
    """剔掉合成语料事件, 返回 (searches, gets, 被剔条数, 被剔 caller 集合)。

    get 按同一 caller 集合一起剔: 只剔 search 会让"消费率"分母被剔而分子不剔。
    计数含 gets(面板口径: "剔除 N 条测试事件")。
    """
    bad = synthetic_callers(searches)
    if not bad:
        return searches, gets, 0, bad
    cs = [s for s in searches if s.get("caller_repo") not in bad]
    cg = [g for g in gets if g.get("caller_repo") not in bad]
    return cs, cg, (len(searches) - len(cs)) + (len(gets) - len(cg)), bad


def _rule_hits(ev: dict, rule: dict) -> bool:
    """单条隔离规则是否命中该事件(条件 AND; 语义见 trace.load_quarantine)。"""
    kind = ev.get("kind")
    if rule.get("kinds") and kind not in rule["kinds"]:
        return False
    if rule.get("caller_repo") is not None and \
            ev.get("caller_repo") != rule["caller_repo"]:
        return False
    day = str(ev.get("ts", ""))[:10]
    if rule.get("since") and day < str(rule["since"]):
        return False
    if rule.get("until") and day > str(rule["until"]):
        return False
    ids = rule.get("ids")
    if ids is not None:
        want = {i for i in ids if isinstance(i, str)} if isinstance(ids, list) else set()
        got = {ev["id"]} if isinstance(ev.get("id"), str) else set()
        got |= {i for i in (ev.get("returned") or []) if isinstance(i, str)}
        if not (want & got):
            return False
    if "max_scanned" in rule:
        if kind != "search":
            return False
        ls = ev.get("layers") or []
        mx = max((int(ly.get("scanned") or 0) for ly in ls if isinstance(ly, dict)),
                 default=-1)
        if mx < 0:            # 无层信息: 不判(缺层≠小扫描, 见 not_executed)
            return False
        try:
            if mx > int(rule["max_scanned"]):
                return False
        except (TypeError, ValueError):
            return False
    return True


def quarantine_events(searches: list[dict], gets: list[dict],
                      rules: list[dict] | None = None) -> tuple[list, list, dict]:
    """按显式清单(及写时 `synthetic` 标记)隔离事件, 返回 (searches, gets, 审计)。

    与 `synthetic_callers` 的分工: 后者只能整 caller 剔, 遇到 `caller_repo=docs`
    这种"真实仓名被 conftest 夹具复用"的混合 caller 必然二选一地误伤; 清单是
    事件级(按 id / 扫描规模 / 日期), 只剔登记过的历史夹具事件。

    三处口径一致: 命中规则的事件从聚合输入里移除, 但**不删不改账本**(raw=1
    仍能看全量); 审计按规则给出各自条数, 面板据此显示"隔离 N 条(理由)"。
    """
    rules = [r for r in (rules or []) if isinstance(r, dict)]
    # 无规则也要走一遍: 写时标记(synthetic=true)不依赖清单文件存在。
    per = [{"why": r.get("why", ""), "searches": 0, "gets": 0,
            "evidence": r.get("evidence", "")} for r in rules]
    flagged = {"why": "synthetic-flag(写时标记)", "searches": 0, "gets": 0,
               "evidence": "append_event 在 pytest 会话内自动打 synthetic=true"}
    out_s: list[dict] = []
    out_g: list[dict] = []
    for batch, dst, key in ((searches, out_s, "searches"),
                            (gets, out_g, "gets")):
        for ev in batch:
            hit = next((i for i, r in enumerate(rules) if _rule_hits(ev, r)), None)
            if hit is not None:
                per[hit][key] += 1
            elif ev.get("synthetic") is True:
                flagged[key] += 1
            else:
                dst.append(ev)
    detail = [p for p in per if p["searches"] or p["gets"]]
    if flagged["searches"] or flagged["gets"]:
        detail.append(flagged)
    return out_s, out_g, {"dropped": sum(p["searches"] + p["gets"] for p in detail),
                          "detail": detail, "flagged": flagged["searches"] + flagged["gets"]}


def denoise_full(searches: list[dict], gets: list[dict],
                 rules: list[dict] | None = None) -> tuple[list, list, dict]:
    """两级剔噪一次做完: ① caller 级启发式 ② 事件级清单/写时标记。

    返回 (searches, gets, audit), audit 把两级条数分开给——面板要能说清"剔了多少"
    里哪些是猜的(caller 启发式)、哪些是登记的(隔离清单), 混成一个数就没法自查。
    """
    cs, cg, n, bad = denoise(searches, gets)
    qs, qg, qa = quarantine_events(cs, cg, rules)
    return qs, qg, {"caller_dropped": n, "callers": sorted(bad),
                    "quarantine_dropped": qa["dropped"],
                    "quarantine_detail": qa["detail"],
                    "dropped": n + qa["dropped"]}



def _later(a: str, b: str) -> str:
    """取两时刻串中真实更晚者(返回原串, 不丢偏移信息)。"""
    return a if _ts_key(a) >= _ts_key(b) else b


def _age_days(ts) -> float | None:
    """时刻距今天数(UTC 时刻差, 不做日粒度取整); 无法解析返回 None = 不判新鲜度。

    旧实现用 `date.today() - ts[:10]`: 被减数是查看机本地日, 减数是写入机本地日,
    跨时区成员混基准; 且日粒度相减把"13.9 天前"当成 14 天整, 与 14d 门槛比对时
    边界抖一天。
    """
    k = _ts_key(ts)
    if not k[0]:
        return None
    return (dt.datetime.now(dt.timezone.utc).timestamp() - k[2]) / 86400


def in_window(events: list[dict], since: str | None = None,
              until: str | None = None) -> list[dict]:
    """榜单类聚合的窗口过滤(与 aggregate 同一 _within 口径)。

    第十一轮走查实测(§29): 窗口按钮只作用于 KPI——零命中榜/UI 空态自己写着
    "窗口内"、热门消费与联邦矩阵同样在窗口工具旁, 但实现全是全量。
    切到 7 天窗口后 KPI 说 1 次检索、同屏矩阵/榜单却数着 20 天前的事件,
    同屏两口径。榜单/矩阵的统计列一律先过本函数再聚合。
    """
    if not since and not until:
        return events
    return [e for e in events if _within(e, since, until)]


def _gets_by_trace(gets: list[dict]) -> dict[str, set[str]]:
    """trace_id → 该 trace 内 ok 的 get id 集合(一次建索引, 免逐 search 全量扫 gets)。"""
    out: dict[str, set[str]] = {}
    for g in gets:
        tid = g.get("trace_id")
        gid = g.get("id")
        # §67 生产者-消费者全链(第五十轮): id 是 §52 净化可删键, 此前裸 add 把
        # None 塞进消费集合——下游一半 `x in consumed` 判真后 `g["id"]` KeyError
        # (top_consumed), 一半 sorted() 遇 None+str 混合 TypeError(feed read)。
        # 集合语义要求元素是 str, 在唯一的入口守一次, 消费方不再逐点补防。
        if tid and g.get("ok") and isinstance(gid, str):
            out.setdefault(tid, set()).add(gid)
    return out


def _consumed_ids(searches: list[dict], gets: list[dict]) -> set[str]:
    """消费口径: 被返回 且 同 trace_id 有 ok 的 get(与 UI"已读"态同一判定)。"""
    by_tid = _gets_by_trace(gets)
    out: set[str] = set()
    for s in searches:
        got = by_tid.get(s.get("trace_id") or "")
        if got:
            out.update(i for i in s.get("returned", []) if i in got)
    return out


def usage_by_id(searches: list[dict], gets: list[dict]) -> dict[str, dict]:
    """id → 使用数据(hits=被 returned 次数, reads=消费读全文次数, last=最近被读/返回 ts)。

    口径与 top_consumed/dead_weight 完全一致: reads 用 _consumed_ids 同判定(被返回
    且同 trace_id 有 ok 的 get), 只是从"取 top N"改成"按 id 全量聚合", 供 B3 质量清单
    每行反查使用度(draft 天天被命中=优先审, 从没被检索=可缓)。hits 计所有 returned
    出现次数(含未消费), reads 只计消费读。
    """
    consumed = _consumed_ids(searches, gets)
    hits: dict[str, int] = {}
    last: dict[str, str] = {}
    for s in searches:
        ts = str(s.get("ts", ""))
        for i in s.get("returned", []):
            if not isinstance(i, str):
                continue
            hits[i] = hits.get(i, 0) + 1
            if _ts_key(ts)[0]:
                last[i] = _later(last.get(i, ""), ts)
    # reads 与 top_consumed.count 同一判定: g.ok 且 id 在全局消费集合内
    reads: dict[str, int] = {}
    for g in gets:
        gid = g.get("id")
        if g.get("ok") and isinstance(gid, str) and gid in consumed:
            reads[gid] = reads.get(gid, 0) + 1
    out: dict[str, dict] = {}
    for i in set(hits) | set(reads):
        out[i] = {"hits": hits.get(i, 0), "reads": reads.get(i, 0),
                  "last": last.get(i, "")}
    return out


def denoise_detail(searches: list[dict], gets: list[dict]) -> list[dict]:
    """每个被判合成 caller 的审计明细(供 raw=1 原始口径自证判据有没有误伤)。

    raw=1 的唯一用途就是"看剔噪误伤没误伤", 但原始口径下 denoise 不生效、计数恒 0,
    用户只能拿两态 KPI 相减反推。这里按判据逐 caller 给出 events / max_scanned /
    why, 其中 tiny-scan 判据正是可能误伤真实小库的那条, 必须显式可见。
    """
    bad = synthetic_callers(searches)
    if not bad:
        return []
    seen: dict[str, int] = {}
    for s in searches:
        c = s.get("caller_repo")
        if c in bad:
            ls = s.get("layers") or []
            mx = max((int(ly.get("scanned") or 0) for ly in ls if isinstance(ly, dict)),
                     default=0)
            seen[c] = max(seen.get(c, 0), mx)
    out = []
    for c in sorted(bad):
        n = (sum(1 for s in searches if s.get("caller_repo") == c)
             + sum(1 for g in gets if g.get("caller_repo") == c))
        mx = seen.get(c, 0)
        named = bool(_TEST_CALLER.match(c))
        why = []
        if named:
            why.append("pytest-tmp-name")
        if mx <= _SYNTH_MAX_SCAN:
            why.append("tiny-scan")
        out.append({"caller": c, "events": n, "max_scanned": mx,
                    "why": "+".join(why) or "tiny-scan"})
    return out


def aggregate(searches: list[dict], gets: list[dict], *,
              since: str | None = None, until: str | None = None) -> dict:
    """FR-1.2 KPI 聚合。事件按 ts 日粒度过滤[since, until]闭区间, None 不限。

    未真正执行的 search(not_executed)不进命中率分母, 其条数单列
    `not_executed_count` 供面板如实标注——剔噪是改口径, 不是抹事件。
    """
    W = [s for s in searches if _within(s, since, until)]
    S = effective(W)
    skipped = len(W) - len(S)
    G = [g for g in gets if _within(g, since, until)]
    n = len(S)
    hit = [s for s in S if s.get("returned")]
    returned_total = sum(len(s.get("returned", [])) for s in S)
    consumed = _consumed_ids(S, G)
    overhead_chars = sum(int(s.get("returned_chars") or 0) for s in S)

    # 层级读取/只看元数据: 判定与消费率同源(同 trace_id 且有 ok 的 get), 只是从
    # "条目"上卷到"这次检索"。有返回但一次全文都没读 = 只停留在 L2(元数据),
    # 显式出数后不必再从 returned_chars 反推; 两侧之和 = 有返回的检索数。
    by_tid = _gets_by_trace(G)

    def _read_after(s: dict) -> bool:
        got = by_tid.get(s.get("trace_id") or "")
        return bool(got) and any(i in got for i in s.get("returned", []))

    meta_only = [s for s in hit if not _read_after(s)]
    to_full = [s for s in hit if _read_after(s)]
    l3_ok = [g for g in G if g.get("ok")]
    l3_chars = sum(int(g["chars"]) for g in l3_ok
                   if isinstance(g.get("chars"), (int, float)))

    def _rc(evs: list[dict]) -> int:
        return sum(int(x.get("returned_chars") or 0) for x in evs)

    def _ret(evs: list[dict]) -> int:
        return sum(len(x.get("returned", [])) for x in evs)

    # 估算节省: 消费 get 的全文 chars − 对应 search 返回的摘要 chars 摊额(按条目均摊)
    saved_chars = 0
    saved_unknown = 0
    by_trace = {s.get("trace_id"): s for s in S if s.get("trace_id")}
    for g in G:
        if not g.get("ok") or g.get("id") not in consumed:
            continue
        s = by_trace.get(g.get("trace_id"))
        chars, rc = g.get("chars"), (s or {}).get("returned_chars")
        n_ret = len((s or {}).get("returned", []))
        if chars is None or s is None or rc is None or n_ret == 0:
            saved_unknown += 1
            continue
        saved_chars += max(int(chars) - int(rc) // n_ret, 0)

    by_caller: dict[str, dict] = {}
    by_day: dict[str, dict] = {}
    for s in S:
        c = by_caller.setdefault(s.get("caller_repo") or "?",
                                 {"searches": 0, "hits": 0, "last_ts": ""})
        c["searches"] += 1
        c["hits"] += 1 if s.get("returned") else 0
        c["last_ts"] = _later(c["last_ts"], str(s.get("ts", "")))
        d = by_day.setdefault(str(s.get("ts", ""))[:10], {"searches": 0, "hits": 0})
        d["searches"] += 1
        d["hits"] += 1 if s.get("returned") else 0

    # 消费率可采集性: 窗口内落在 CLI 埋点起点之前的检索数是不可观测的 reader 流量。
    # 全在之前 → tracked=False(指标应显示"未采集"而不是 0.0%); 部分重叠 → 值是下界。
    pre_tracking = sum(1 for s in S
                       if str(s.get("ts", ""))[:10] < CONSUME_TRACKING_SINCE)

    return {
        "window": {"since": since, "until": until},
        "searches": n,
        "not_executed_count": skipped,  # 未扫库的空事件(见 not_executed), 已从分母剔除
        "hit_rate": round(len(hit) / n, 4) if n else None,
        "returned_total": returned_total,
        "consumed_total": len(consumed),
        "consume_rate": round(len(consumed) / returned_total, 4) if returned_total else None,
        # 消费率可采集性(CLI kb show 埋点前无 reader 记录): tracked=False 表示本窗口
        # 的消费率完全没被观测过, UI 必须显示"未采集"; pre_tracking_searches>0 且
        # tracked=True 表示部分覆盖, 数值只是下界。
        "consume_tracked_from": CONSUME_TRACKING_SINCE,
        "consume_tracked": bool(n) and pre_tracking == 0,
        "pre_tracking_searches": pre_tracking,
        "get_events": len(G),           # 窗口内 get 事件数(消费侧原始计数, 便于对账)
        # 层级读取(三级披露): L1 无服务面 → 恒 0 且 observable=false; L2 每次 search,
        # L3 每次 get(ok_events 是成功读到的次数)。declared 是带显式 surface 的事件数,
        # 与 events 的差额说明有多少旧事件靠 kind 兜底(自 LAYER_TRACKING_SINCE 起才有)。
        "layer_reads": {
            "l1": {"events": 0, "observable": False, "surface": "AGENTS.md",
                   "note": "宿主装载, kb 进程不参与, 无读取事件"},
            "l2": {"events": n, "chars": overhead_chars, "surface": SURFACE_SEARCH,
                   "declared": sum(1 for s in S
                                   if s.get("surface") == SURFACE_SEARCH)},
            "l3": {"events": len(G), "ok_events": len(l3_ok), "chars": l3_chars,
                   "surface": SURFACE_GET,
                   "declared": sum(1 for g in G
                                   if g.get("surface") == SURFACE_GET)},
        },
        "layer_tracking_since": LAYER_TRACKING_SINCE,
        # 只看元数据 vs 续读全文: 按"这次检索有没有被同 trace 读走任一条目"切分,
        # 与消费率同源判定。字符数取各自事件的 returned_chars, 相加 + 零命中事件
        # 的 returned_chars = overhead_chars(可与"知识库自身开销"对账)。
        "meta_only": {"searches": len(meta_only), "chars": _rc(meta_only),
                      "returned": _ret(meta_only)},
        "meta_to_full": {"searches": len(to_full), "chars": _rc(to_full),
                         "returned": _ret(to_full)},
        "saved_chars_est": saved_chars,
        "saved_unknown_count": saved_unknown,  # schema=1 老事件无 chars → 保守不计
        "overhead_chars": overhead_chars,
        "by_caller": by_caller,
        "by_day": [dict(day=k, **v) for k, v in sorted(by_day.items())],
        # 冷启动门槛(PRD 开放问题3): 连续数据 <7 天不出命中率趋势, 只出绝对计数
        "cold_start": len({str(s.get("ts", ""))[:10] for s in S}) < 7,
    }


def latency(searches: list[dict], *, since: str | None = None,
            until: str | None = None) -> dict:
    """耗时聚合(P50/P95/均值/最慢): 事件级 duration_ms 此前只在逐行流水里显示,
    检索整体变慢只能肉眼看列表, 无任何聚合口径。缺 duration_ms 的事件不计
    (老 schema 事件不冒充 0ms)。"""
    d = sorted(int(s["duration_ms"]) for s in searches
               if _within(s, since, until) and isinstance(s.get("duration_ms"), (int, float)))
    if not d:
        return {"n": 0, "p50_ms": None, "p95_ms": None,
                "avg_ms": None, "max_ms": None}

    def pctl(x: float) -> int:
        import math
        return d[min(len(d) - 1, math.ceil(x / 100 * len(d)) - 1)]

    return {"n": len(d), "p50_ms": pctl(50), "p95_ms": pctl(95),
            "avg_ms": round(sum(d) / len(d)), "max_ms": d[-1]}


def top_queries(searches: list[dict], *, limit: int = 10) -> list[dict]:
    """热门被消费 query(按命中次数); 面板榜单用。

    limit 契约(§58 同族, 第四十六轮): ≤0 零名额——负数切片 `[:-2]` 是"去尾"
    不是"取前 -2", "要最少给最多"翻转(top_consumed/zero_hit_board 同修)。
    """
    cnt: dict[str, int] = {}
    for s in searches:
        if s.get("returned") and s.get("query"):
            cnt[s["query"]] = cnt.get(s["query"], 0) + 1
    rows = [{"query": q, "count": c}
            for q, c in sorted(cnt.items(), key=lambda x: -x[1])]
    return rows[:limit] if limit > 0 else []


def top_consumed(searches: list[dict], gets: list[dict], *,
                 limit: int = 10) -> list[dict]:
    """热门被消费条目: id → 消费次数 + 最新标题(事件自含, 不回查索引)。"""
    titles: dict[str, str] = {}
    for s in searches:
        for ly in s.get("layers", []):
            for m in ly.get("matched", []):
                if m.get("id") and m.get("title"):
                    titles[m["id"]] = m["title"]
    consumed = _consumed_ids(searches, gets)
    cnt: dict[str, int] = {}
    for g in gets:
        if g.get("ok") and g.get("id") in consumed:
            cnt[g["id"]] = cnt.get(g["id"], 0) + 1
    rows = [{"id": i, "title": titles.get(i, ""), "count": c}
            for i, c in sorted(cnt.items(), key=lambda x: -x[1])]
    return rows[:limit] if limit > 0 else []  # limit 契约同 top_queries(§58 同族)


def dead_weight(searches: list[dict], gets: list[dict], *, limit: int = 10,
                min_returned: int = 3) -> list[dict]:
    """A6 高返回零消费榜: 窗口内被 returned 次数高、却从未被同 trace 读全文的条目。

    消费率是单个百分比, 低在哪些条目上看不出来 —— 本榜回答"该砍谁"。口径与
    `_consumed_ids` 完全一致(被返回 且 同 trace_id 有 ok 的 get 才算消费), 只是
    取补集: 出现在 returned 里但不在消费集合内的条目, 按返回次数倒序。
    min_returned 过滤只被返回过 1-2 次的长尾(噪声), 避免榜单被偶发命中刷屏。

    解读边界: "零消费"不等于"条目没用"——摘要可能就够 agent 决策了(这本身是
    kb 的设计目的: 摘要判相关性, 全文按需读)。榜单指向的是**摘要性价比**问题
    (摘要写了却没人想读全文), 不是删除依据。
    """
    titles: dict[str, str] = {}
    for s in searches:
        for ly in s.get("layers", []):
            for m in ly.get("matched", []):
                if m.get("id") and m.get("title"):
                    titles[m["id"]] = m["title"]
    consumed = _consumed_ids(searches, gets)
    cnt: dict[str, int] = {}
    last: dict[str, str] = {}
    for s in searches:
        for i in s.get("returned", []):
            if not isinstance(i, str) or i in consumed:
                continue
            cnt[i] = cnt.get(i, 0) + 1
            ts = str(s.get("ts", ""))
            if _ts_key(ts)[0]:
                last[i] = _later(last.get(i, ""), ts)
    rows = [{"id": i, "title": titles.get(i, ""), "returned": c,
             "last_ts": last.get(i, "")}
            for i, c in cnt.items() if c >= min_returned]
    rows.sort(key=lambda r: -r["returned"])
    return rows[:limit] if limit > 0 else []


def zero_hit_board(searches: list[dict], *, limit: int = 10) -> list[dict]:
    """零命中榜 + 已消化判定: 同 caller 在**该次失败之后**(ts 不早于失败)出现命中,
    且命中词覆盖原 query(或其 suggest 词)。

    时间方向性(第十七轮走查): 旧实现全量预扫不分先后, "先命中后失败"的词(条目被
    降级/删除/改名后检索不到)仍被标已消化 → 待消化榜漏掉恰恰最该补的词。
    suggest 挂在**失败事件**上(build_search_event 零命中时透传), 旧实现从命中事件
    读 s.get("suggest") 恒为 None, suggest 消化路径从未生效。

    入参先过 effective(): 未扫库的空事件不是"库里没有答案", 上榜会把 FR-3.5 的
    补库回路指向错词(历史 traces 榜首「vite」×105 全是这类噪声, 同窗真实命中 231)。
    """
    searches = effective(searches)
    hits_by_caller: dict[str, list[tuple[str, set[str]]]] = {}
    for s in searches:
        if not s.get("returned"):
            continue
        toks: set[str] = set()
        q = (s.get("query") or "").strip().lower()
        if q:
            toks.add(q)          # 完整 query 串命中 = 最直接的同词消化
            toks.update(q.split())  # 单 token 命中也算消化(agent 改查单词)
        if toks:
            hits_by_caller.setdefault(s.get("caller_repo") or "?", []).append(
                (str(s.get("ts", "")), toks))
    board: dict[str, dict] = {}
    for s in searches:
        if s.get("returned") or not s.get("query"):
            continue
        q = s["query"].strip().lower()
        ts = str(s.get("ts", ""))
        sug = {str(w).strip().lower() for w in (s.get("suggest") or [])}
        digested = any(_ts_key(hts) >= _ts_key(ts) and (q in toks or (sug and sug & toks))
                       for hts, toks in hits_by_caller.get(
                           s.get("caller_repo") or "?", []))
        if q not in board:
            board[q] = {"query": q, "count": 1, "caller": s.get("caller_repo"),
                        "last_ts": ts, "digested": digested}
        else:
            row = board[q]
            row["count"] += 1
            row["last_ts"] = _later(row["last_ts"], ts)
            # AND 语义: 任一次失败之后没有命中(某 caller 现状仍未解决), 该词就该留在榜上
            row["digested"] = row["digested"] and digested
    rows = sorted(board.values(), key=lambda r: -r["count"])
    return rows[:limit] if limit > 0 else []  # limit 契约同 top_queries(§58 同族)


def feed_events(searches: list[dict], gets: list[dict], *, caller: str | None = None,
                limit: int = 50, since: str | None = None,
                until: str | None = None, offset: int = 0) -> list[dict]:
    """实时流的初始快照: 最近 N 条 search(含其关联 get 的已读标注)。

    details: 每个返回条目 → {repo: 来源层, hit_fields} —— 蜘蛛动画按来源层配色
    (项目层绿 / 通用层橙), read 命中的再叠加"已读"黄覆盖层。

    since/until(2026-11-02 A2): 与同屏 KPI 同窗口口径(_within 日粒度)。此前
    feed 固定拉全时最近 500 条, 切窗口时 KPI 变、列表不变, 同屏两口径——
    KPI 说"近 7 天 12 次检索", 列表却混排着 20 天前的行, 用户无从分辨。
    SSE 增量只推写入即时的事件(必在窗口内), 无需在客户端二次过滤。
    """
    S = [s for s in searches
         if (not caller or s.get("caller_repo") == caller) and _within(s, since, until)]
    got_by_tid = _gets_by_trace(gets)
    out = []
    # limit 契约(§58 同族第四处, 第四十二轮): 负数切片 `[:-2]` 是"去尾"不是
    # "取前 -2", 语义翻转为"要最少给最多"; ≤0 一律零名额(read_traces 同款)。
    # offset 游标(S1): 面板"加载更多"追加——排序后切片 [start:start+limit], 与
    # 单次 limit 同序同源, 翻页不会漏/重。
    order = sorted(S, key=lambda e: _ts_key(e.get("ts")), reverse=True)
    start = offset if offset > 0 else 0
    for s in (order[start:start + limit] if limit > 0 else []):
        tid = s.get("trace_id")
        returned = s.get("returned", [])
        ret_set = set(returned)
        details: dict[str, dict] = {}
        for ly in s.get("layers", []):
            for m in ly.get("matched", []):
                mid = m.get("id")
                if mid in ret_set and mid not in details:
                    details[mid] = {"repo": ly.get("repo"),
                                    "hit_fields": m.get("hit_fields") or [],
                                    "title": m.get("title") or ""}
        out.append({
            "trace_id": tid, "ts": s.get("ts"), "caller": s.get("caller_repo"),
            "query": s.get("query"), "duration_ms": s.get("duration_ms"),
            "returned": returned,
            "details": details,
            "read": sorted(got_by_tid.get(tid or "", ())),
            "layers": [{"repo": ly.get("repo"), "scanned": ly.get("scanned"),
                        "rejected": ly.get("rejected")} for ly in s.get("layers", [])],
        })
    return out


def callers(searches: list[dict], *, since: str | None = None,
            until: str | None = None) -> list[dict]:
    """联邦视图项目矩阵行: caller + 存活检测(最近活跃距今 >14d = stale)
    + 按源堆叠(by_source) + 外接源健康(ext, 来自 trace ext 字段)。

    第十一轮走查(§29): 检索数/命中率/按源堆叠等**统计列**跟随时间窗口
    (与同屏 KPI 同口径); 但**活跃性**(last_ts/stale/ext 健康)刻意保持全量——
    "掉线检测"看的是该 caller 最后一次真实活动, 若被窗口过滤, 切 7 天窗口
    会把 8 天前活跃的项目误报成"从未活跃", 语义错误。
    """
    win = in_window(searches, since, until)
    src = by_source(win)
    ext_health = _ext_health_latest(searches)  # 全量: 健康度与活跃性同理不随窗口
    byc_win = aggregate(win, []).get("by_caller", {})
    # 行集 = 有效事件里出现过的 caller(窗口外才活跃的项目必须留在矩阵里显 stale,
    # 否则 7 天窗口会把"掉线项目"整行抹掉, 掉线检测反而失效)。
    # 过 effective(): 未扫库的空事件不算"这个项目活跃过"——历史 traces 里 pytest
    # 合成 caller(test_cli_*、proj、docs)正是靠这类空事件混进了矩阵行。
    all_callers: dict[str, str] = {}
    for s in effective(searches):
        c = s.get("caller_repo") or "?"
        all_callers[c] = _later(all_callers.get(c, ""), str(s.get("ts", "")))
    rows = []
    for c, all_ts in all_callers.items():
        v = byc_win.get(c, {"searches": 0, "hits": 0})
        age = _age_days(all_ts)
        stale = age is not None and age > 14
        rows.append({"caller": c, "searches": v["searches"],
                     "hit_rate": (round(v["hits"] / v["searches"], 4)
                                  if v["searches"] else None),
                     "last_ts": all_ts, "stale": stale,
                     "by_source": src.get(c, {}),
                     "ext": ext_health.get(c, [])})
    return sorted(rows, key=lambda r: -r["searches"])


def source_of(hit_id: str, layers: list[dict]) -> str:
    """命中 id → 源名: source://<connector>/<原生id> → "ext:<connector>";
    否则按 layers 中该 id 所在层 repo(项目层约定 docs, 由调用方传 proj_repo 区分)。"""
    if str(hit_id).startswith("source://"):
        return "ext:" + str(hit_id)[len("source://"):].split("/", 1)[0]
    return None  # 本地命中由调用方按层归类


def by_source(searches: list[dict]) -> dict:
    """FR-5.2 按源堆叠: caller → {源名: 命中次数}。

    源名: "project"(首层=项目层) / "stack"(其余本地层, 即通用层) /
    "ext:<connector>"(外接源, 取自 returned 的 source:// 前缀 + ext.hits)。
    计数口径 = 每次 search 事件返回(returned)条目的归属, 与 KPI 命中率同源。
    """
    out: dict[str, dict[str, int]] = {}
    for s in searches:
        caller = s.get("caller_repo") or "?"
        row = out.setdefault(caller, {})
        layers = s.get("layers", [])
        ext_ids: set[str] = set()
        for e in s.get("ext", []) or []:
            ext_ids.update(e.get("hits", []))
        # id → 层序 一次建索引, 避免逐 returned 条目重扫全部层的全部 matched
        layer_of: dict[str, int] = {}
        for i, ly in enumerate(layers):
            for m in ly.get("matched", []):
                layer_of.setdefault(m.get("id"), i)
        for hid in s.get("returned", []):
            if hid in ext_ids or str(hid).startswith("source://"):
                name = source_of(hid, layers) or "ext:?"
            else:
                i = layer_of.get(hid)
                name = "stack" if i is None else ("project" if i == 0 else "stack")
            row[name] = row.get(name, 0) + 1
    return out


def _ext_health_latest(searches: list[dict]) -> dict:
    """caller → 最近一次 ext 健康记录(源名/ok/error), 矩阵"外接·源"列用。"""
    out: dict[str, dict[str, dict]] = {}
    for s in sorted(searches, key=lambda e: _ts_key(e.get("ts"))):
        caller = s.get("caller_repo") or "?"
        for e in s.get("ext", []) or []:
            src = e.get("source") or "?"
            out.setdefault(caller, {})[src] = {
                "source": src, "ok": bool(e.get("ok")), "error": e.get("error")}
    return {c: list(v.values()) for c, v in out.items()}
