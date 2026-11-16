"""周指标快照层 — 长周期观测的凝固点。

设计: docs/superpowers/specs/2026-11-11-kb-longrun-metrics-design.md(方案 A)

职责边界:
- 指标口径**零新计算**, 全部委托 kb.stats(唯一实现), 本模块只做切周/编排/落盘/读取;
- 快照落 traces/metrics/YYYY-Www.json, 是不可变账本: 已存在即拒绝重写(--force 除外),
  否则"上周报的命中率"会在下周变成另一个数, 长周期趋势失去意义;
- 消化工单只产出**建议清单**, 零写库: 落库必须走 kb new / kb review 门控(AGENTS.md 红线)。
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from kb import search as kbsearch
from kb import stats
from kb import trace as kbtrace
from kb.fskit import write_text_lf

SCHEMA = 1
_BOARD_LIMIT = 30      # 与 kb trace report 的榜单上限一致
_PLAN_LIMIT = 10       # 工单清单上限(周报可读性优先, 全量走快照 JSON 自查)

# 周号严格 YYYY-Www: `2026-45`/`2026-W4` 会被静默错解成别的周,
# 与 cli._date_arg 同族的"入口即拒"原则 —— 不把坏值放进数据面。
_WEEK = re.compile(r"^(\d{4})-W(\d{2})$")


def week_bounds(week: str) -> tuple[str, str]:
    """`YYYY-Www` → (周一, 周日) ISO 日期串。非法值 ValueError(调用面在 argparse 即拒)。"""
    m = _WEEK.match(week or "")
    if not m:
        raise ValueError(f"需 YYYY-Www 周号(如 2026-W45), 收到 {week!r}")
    y, w = int(m.group(1)), int(m.group(2))
    try:
        mon = dt.date.fromisocalendar(y, w, 1)
        sun = dt.date.fromisocalendar(y, w, 7)
    except ValueError:
        raise ValueError(f"非法 ISO 周: {week!r}") from None
    return mon.isoformat(), sun.isoformat()


def prev_of(week: str) -> str:
    """上一 ISO 周号。周一回推 3 天必落在上一周(周日)→ isocalendar 天然跨年/跨 53 周。"""
    mon = dt.date.fromisoformat(week_bounds(week)[0])
    y, w, _ = (mon - dt.timedelta(days=3)).isocalendar()
    return f"{y}-W{w:02d}"


def prev_week(today: dt.date | None = None) -> str:
    """默认口径: 上一个**完整**自然周(本周还没跑完, 拿它出周报是半窗数据)。"""
    y, w, _ = (today or dt.date.today()).isocalendar()
    return prev_of(f"{y}-W{w:02d}")


def metrics_dir(root: Path | None = None) -> Path:
    return kbtrace.traces_dir(root) / "metrics"


def snapshot_path(root: Path | None, week: str) -> Path:
    return metrics_dir(root) / f"{week}.json"


def build_snapshot(root: Path | None, week: str) -> dict:
    """聚合某自然周的指标(口径全在 stats)。入参先过 denoise —— 与面板/KPI 同口径,
    否则快照会把 pytest 合成语料算进分母(2026-11-02 实测污染 25%)。

    callers 传的是 denoise 后的**全量**事件而非 win_s: stats.callers 内部自己切窗
    算统计列, 但行集与活跃性刻意看全量(见其 docstring §29)——若在这里先切窗,
    只在窗口外活跃的项目会整行消失, "掉线项目"在快照里永久不可见。"""
    since, until = week_bounds(week)
    searches, gets, warns = kbtrace.read_traces(root)
    rules, qwarns = kbtrace.load_quarantine(root)
    warns = warns + qwarns
    searches, gets, _n, _bad = stats.denoise(searches, gets)
    # 事件级隔离清单: 与面板默认口径一致, 否则周报会把 caller=docs 下混着的
    # 历史夹具事件(真实仓名被 conftest 复用, 整 caller 剔不掉)照旧算进消费率。
    searches, gets, _ = stats.quarantine_events(searches, gets, rules)
    win_s = stats.in_window(searches, since, until)
    win_g = stats.in_window(gets, since, until)
    board = stats.zero_hit_board(win_s, limit=_BOARD_LIMIT)
    dig = [r for r in board if r.get("digested")]
    return {
        "schema": SCHEMA,
        "week": week,
        "since": since,
        "until": until,
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "metrics": stats.aggregate(win_s, win_g, since=since, until=until),
        "latency": stats.latency(win_s, since=since, until=until),
        "zero_hit": {"board": board, "digested": len(dig),
                     "digest_rate": round(len(dig) / len(board), 4) if board else None},
        "callers": stats.callers(searches, since=since, until=until),
        "warns": warns,
    }


def write_snapshot(root: Path | None, snap: dict, *, force: bool = False) -> Path:
    """落盘。已存在且未 force → FileExistsError(CLI 转成退 1 + 人话)。"""
    p = snapshot_path(root, snap["week"])
    if p.exists() and not force:
        raise FileExistsError(
            f"快照已存在(不可变账本): {p}\n"
            f"  确要按当前账本重写请加 --force(会改变历史周报口径, 需在评审说明)")
    p.parent.mkdir(parents=True, exist_ok=True)
    write_text_lf(p, json.dumps(snap, ensure_ascii=False, indent=2) + "\n")
    return p


# 快照子对象期望类型(缺省键允许, 存在则必须对): 消费面用 .get(...), 类型错就 500。
_SNAP_SHAPES = (("metrics", dict), ("latency", dict), ("zero_hit", dict),
                ("callers", list), ("warns", list))


def load_snapshots(root: Path | None) -> tuple[list[dict], list[str]]:
    """读全部周快照, 按周号升序。坏文件跳过并计 warns —— 一个手改坏的快照
    不该让整条趋势线与 /api/metrics 500(stats §26/§50 同族教训)。"""
    d = metrics_dir(root)
    if not d.exists():
        return [], []
    out: list[dict] = []
    warns: list[str] = []
    for f in sorted(d.glob("*.json")):
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:   # JSONDecodeError 是 ValueError 子类
            warns.append(f"{f.name}: 快照不可读({exc}), 已跳过")
            continue
        if not isinstance(obj, dict) or not obj.get("week"):
            warns.append(f"{f.name}: 缺 week 字段, 已跳过")
            continue
        # 子对象类型也要校验: 合法 JSON 但 `"metrics": [1,2]` 会让消费方
        # (.get(...)) 抛 AttributeError → /api/metrics 500, 同样只降级为 warns。
        bad = next(((k, t) for k, t in _SNAP_SHAPES
                    if k in obj and not isinstance(obj[k], t)), None)
        if bad:
            warns.append(f"{f.name}: 子对象 {bad[0]} 类型应为 {bad[1].__name__}, 已跳过")
            continue
        out.append(obj)
    out.sort(key=lambda o: str(o["week"]))
    return out, warns


# 环比字段: (展示名, 取值路径)。任一侧非数值 → diff=None(只报绝对值, 不猜)。
_DELTA_SPEC = (("searches", ("metrics", "searches")),
               ("hit_rate", ("metrics", "hit_rate")),
               ("consume_rate", ("metrics", "consume_rate")),
               ("digest_rate", ("zero_hit", "digest_rate")),
               ("p50_ms", ("latency", "p50_ms")))


def _pick(snap: dict | None, path: tuple[str, str]):
    v = (snap or {}).get(path[0], {})
    v = v.get(path[1]) if isinstance(v, dict) else None
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def delta(cur: dict, prev: dict | None) -> dict:
    """环比: {name: {cur, prev, diff}}。上周快照缺失/该字段无值 → diff=None。"""
    out = {}
    for name, path in _DELTA_SPEC:
        c = _pick(cur, path)
        p = _pick(prev, path) if prev else None
        out[name] = {"cur": c, "prev": p,
                     "diff": None if (c is None or p is None) else round(c - p, 4)}
    return out


def digest_plan(root: Path | None, snap: dict, *, limit: int = _PLAN_LIMIT) -> list[dict]:
    """消化工单**建议**: 未消化零命中词 → 用同一检索面(kb.search, 纯函数无副作用)
    找近似条目。有近似命中 = 词能命中库面但排序/字段没接上 → 补 tags(中英各一组) /
    改 summary; 无近似命中 = 库里确实没答案 → 立新条。

    红线: 本函数不写任何东西。落库由人/agent 走 `kb new --generated`(draft)与
    `kb review`(accepted 须 evidence + confidence 提升), 且追加"新发现"必须同步补 tags。
    """
    plan: list[dict] = []
    for r in (snap.get("zero_hit", {}).get("board") or []):
        if r.get("digested") or len(plan) >= limit:
            continue
        q = str(r.get("query") or "")
        note = ""
        try:
            hits = kbsearch.search(Path(root) if root else kbtrace.kb_root(),
                                   query=q, limit=3)
        except (OSError, ValueError) as exc:
            # 索引缺失/损坏不是错误, 是"库里没有可挂靠条目"这一事实的一部分
            hits, note = [], f"(索引不可用: {exc})"
        if hits:
            action = "补 tags(中英各一组) / 改 summary, 让该词接上既有条目" + note
            targets = [{"id": h.get("id"), "title": h.get("title")} for h in hits]
        else:
            action = "立新条(kb new, 先 kb search 去重)" + note
            targets = []
        plan.append({"query": q, "count": r.get("count"), "caller": r.get("caller"),
                     "last_ts": r.get("last_ts"), "action": action, "targets": targets})
    return plan


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.1f}%"


def report_markdown(snap: dict, prev: dict | None = None,
                    plan: list[dict] | None = None) -> str:
    """周报正文(stdout 展示物, 快照本身不含它)。环比缺失必须**显式标注**——
    沉默的"—"会被读成"没变化"(§58 假数据同族)。"""
    m = snap.get("metrics") or {}
    zh = snap.get("zero_hit") or {}
    la = snap.get("latency") or {}
    d = delta(snap, prev)

    def pp(name: str) -> str:
        v = d[name]["diff"]
        return "环比 —(上周快照缺失)" if v is None \
            else f"环比 {'+' if v >= 0 else ''}{v * 100:.1f}pp"

    def ms(name: str) -> str:
        v = d[name]["diff"]
        return "环比 —(上周快照缺失)" if v is None \
            else f"环比 {'+' if v >= 0 else ''}{v:.0f}ms"

    # 判据是 aggregate 的 cold_start(窗口内有效检索日 <7 天), 文案必须跟着判据说,
    # 否则读者会把门槛理解成"检索次数", 与实际的"连续观测天数"错位。
    cold = " · ⚠ 冷启动(有效检索日 <7 天, 比率不稳)" if m.get("cold_start") else ""
    out = [f"# 知识库周指标 · {snap.get('week')}({snap.get('since')} ~ {snap.get('until')})",
           "",
           f"- 检索 **{m.get('searches') or 0}** 次 · 命中率 **{_pct(m.get('hit_rate'))}**"
           f"({pp('hit_rate')}){cold}",
           f"- 返回→消费率 **{_pct(m.get('consume_rate'))}**({pp('consume_rate')})"
           f" · 零命中消化率 **{_pct(zh.get('digest_rate'))}**({pp('digest_rate')})"]
    out.append(f"- 检索耗时 p50 {la.get('p50_ms')}ms / p95 {la.get('p95_ms')}ms(n={la.get('n')}) {ms('p50_ms')}"
               if la.get("n") else "- 检索耗时: 本周无 duration_ms 样本")
    out += ["", "## 活跃项目"]
    rows = snap.get("callers") or []
    if not rows:
        out.append("- 本周无检索活动")
    for r in rows[:10]:
        out.append(f"- `{r.get('caller')}`: {r.get('searches')} 次 · 命中率 "
                   f"{_pct(r.get('hit_rate'))}"
                   + (" · ⚠ 超 14 天无活动" if r.get("stale") else ""))
    out += ["", "## 消化工单(仅建议 · 落库走 kb new / kb review 门控)"]
    if plan:
        for it in plan:
            tg = "、".join(f"{t['id']}「{t['title']}」" for t in it["targets"]) or "无"
            out.append(f"- 「{it['query']}」×{it['count']}(caller={it.get('caller')}, "
                       f"最近 {str(it.get('last_ts'))[:10]})\n"
                       f"  - 建议: {it['action']}\n  - 候选条目: {tg}")
    else:
        out.append("- 本周待消化零命中: 无 ✅")
    if snap.get("warns"):
        out += ["", f"> ⚠ 读侧告警 {len(snap['warns'])} 条(不影响本表口径): "
              + "; ".join(str(w) for w in snap["warns"][:3])]
    return "\n".join(out)
