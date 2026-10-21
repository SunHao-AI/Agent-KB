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
- 零命中榜   : returned 为空的 search 按 query 频次倒序; 同 caller 后续同 query 或
              suggest 词命中 → 标 digested(已消化)。
"""
from __future__ import annotations

import datetime as dt


def _within(ev: dict, since: str | None, until: str | None) -> bool:
    day = str(ev.get("ts", ""))[:10]
    return not ((since and day < since) or (until and day > until))


def _gets_by_trace(gets: list[dict]) -> dict[str, set[str]]:
    """trace_id → 该 trace 内 ok 的 get id 集合(一次建索引, 免逐 search 全量扫 gets)。"""
    out: dict[str, set[str]] = {}
    for g in gets:
        tid = g.get("trace_id")
        if tid and g.get("ok"):
            out.setdefault(tid, set()).add(g.get("id"))
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


def aggregate(searches: list[dict], gets: list[dict], *,
              since: str | None = None, until: str | None = None) -> dict:
    """FR-1.2 KPI 聚合。事件按 ts 日粒度过滤[since, until]闭区间, None 不限。"""
    S = [s for s in searches if _within(s, since, until)]
    G = [g for g in gets if _within(g, since, until)]
    n = len(S)
    hit = [s for s in S if s.get("returned")]
    returned_total = sum(len(s.get("returned", [])) for s in S)
    consumed = _consumed_ids(S, G)

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
        c["last_ts"] = max(c["last_ts"], str(s.get("ts", "")))
        d = by_day.setdefault(str(s.get("ts", ""))[:10], {"searches": 0, "hits": 0})
        d["searches"] += 1
        d["hits"] += 1 if s.get("returned") else 0

    return {
        "window": {"since": since, "until": until},
        "searches": n,
        "hit_rate": round(len(hit) / n, 4) if n else None,
        "returned_total": returned_total,
        "consumed_total": len(consumed),
        "consume_rate": round(len(consumed) / returned_total, 4) if returned_total else None,
        "saved_chars_est": saved_chars,
        "saved_unknown_count": saved_unknown,  # schema=1 老事件无 chars → 保守不计
        "overhead_chars": sum(int(s.get("returned_chars") or 0) for s in S),
        "by_caller": by_caller,
        "by_day": [dict(day=k, **v) for k, v in sorted(by_day.items())],
        # 冷启动门槛(PRD 开放问题3): 连续数据 <7 天不出命中率趋势, 只出绝对计数
        "cold_start": len({str(s.get("ts", ""))[:10] for s in S}) < 7,
    }


def top_queries(searches: list[dict], *, limit: int = 10) -> list[dict]:
    """热门被消费 query(按命中次数); 面板榜单用。"""
    cnt: dict[str, int] = {}
    for s in searches:
        if s.get("returned") and s.get("query"):
            cnt[s["query"]] = cnt.get(s["query"], 0) + 1
    return [{"query": q, "count": c}
            for q, c in sorted(cnt.items(), key=lambda x: -x[1])[:limit]]


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
    return [{"id": i, "title": titles.get(i, ""), "count": c}
            for i, c in sorted(cnt.items(), key=lambda x: -x[1])[:limit]]


def zero_hit_board(searches: list[dict], *, limit: int = 10) -> list[dict]:
    """零命中榜 + 已消化判定: 同 caller 后续同 query(或其 suggest 词)出现过命中。"""
    hits_by_caller: dict[str, set[str]] = {}
    for s in sorted(searches, key=lambda e: str(e.get("ts", ""))):
        if s.get("returned"):
            toks = hits_by_caller.setdefault(s.get("caller_repo") or "?", set())
            q = (s.get("query") or "").strip().lower()
            if q:
                toks.add(q)  # 完整 query 串命中 = 最直接的同词消化
                toks.update(q.split())  # 单 token 命中也算消化(agent 改查单词)
            for w in (s.get("suggest") or []):
                toks.add(str(w).lower())
    board: dict[str, dict] = {}
    for s in searches:
        if s.get("returned") or not s.get("query"):
            continue
        q = s["query"].strip().lower()
        row = board.setdefault(q, {"query": q, "count": 0, "caller": s.get("caller_repo"),
                                   "last_ts": "", "digested": False})
        row["count"] += 1
        row["last_ts"] = max(row["last_ts"], str(s.get("ts", "")))
        if q in hits_by_caller.get(s.get("caller_repo") or "?", set()):
            row["digested"] = True
    return sorted(board.values(), key=lambda r: -r["count"])[:limit]


def feed_events(searches: list[dict], gets: list[dict], *, caller: str | None = None,
                limit: int = 50) -> list[dict]:
    """实时流的初始快照: 最近 N 条 search(含其关联 get 的已读标注)。

    details: 每个返回条目 → {repo: 来源层, hit_fields} —— 蜘蛛动画按来源层配色
    (项目层绿 / 通用层橙), read 命中的再叠加"已读"黄覆盖层。
    """
    S = [s for s in searches if not caller or s.get("caller_repo") == caller]
    got_by_tid = _gets_by_trace(gets)
    out = []
    for s in sorted(S, key=lambda e: str(e.get("ts", "")), reverse=True)[:limit]:
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


def callers(searches: list[dict]) -> list[dict]:
    """联邦视图项目矩阵行: caller + 存活检测(最近活跃距今 >14d = stale)
    + 按源堆叠(by_source) + 外接源健康(ext, 来自 trace ext 字段)。"""
    today = dt.date.today()
    src = by_source(searches)
    ext_health = _ext_health_latest(searches)
    rows = []
    for c, v in (aggregate(searches, []).get("by_caller", {})).items():
        last = v["last_ts"][:10]
        stale = False
        if len(last) == 10:
            try:
                stale = (today - dt.date.fromisoformat(last)).days > 14
            except ValueError:
                pass
        rows.append({"caller": c, "searches": v["searches"],
                     "hit_rate": round(v["hits"] / v["searches"], 4) if v["searches"] else None,
                     "last_ts": v["last_ts"], "stale": stale,
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
    for s in sorted(searches, key=lambda e: str(e.get("ts", ""))):
        caller = s.get("caller_repo") or "?"
        for e in s.get("ext", []) or []:
            src = e.get("source") or "?"
            out.setdefault(caller, {})[src] = {
                "source": src, "ok": bool(e.get("ok")), "error": e.get("error")}
    return {c: list(v.values()) for c, v in out.items()}
