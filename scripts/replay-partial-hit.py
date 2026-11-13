"""部分命中降级离线回放 — spec 2026-11-13 §4.2 验收门槛的可复现实现。

对 traces/*.jsonl 的历史**有效** query(剔 not_executed 与合成 caller), 在
**当前** kb/index.jsonl 上把新旧两种策略各重放一遍再对比(索引自查询当日
有演进, 只与"同索引下旧策略结果"比, 不与 trace 记录的历史 returned 比):
  1) 旧策略(纯 AND)命中的查询, 新策略结果集与排序 100% 不变;
  2) --week 指定 ISO 周时, 该周新策略 hit_rate ≥ 50%(W46 基线 35.1%);
  3) 打印新旧总 hit_rate 供人工确认"显著提升"。

用法:
  python scripts/replay-partial-hit.py              # 全量语料
  python scripts/replay-partial-hit.py --week 46    # 附 W46 达标判据

退出码: 0=PASS; 1=FAIL(回退或未达标); 2=输入不可用(缺生成物/无语料)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kb.search import _hit, _parts, _score, evaluate  # noqa: E402
from kb.stats import denoise, effective  # noqa: E402


def load_index(repo: Path) -> list[dict]:
    jl = repo / "kb" / "index.jsonl"
    if not jl.exists():
        print(f"缺生成物: {jl}", file=sys.stderr)
        sys.exit(2)
    return [json.loads(x) for x in jl.read_text(encoding="utf-8").splitlines() if x.strip()]


def load_searches(traces: Path) -> list[dict]:
    out: list[dict] = []
    for f in sorted(traces.glob("*.jsonl")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") == "search":
                out.append(rec)
    return out


def iso_week(ts: str) -> int | None:
    try:
        return dt.datetime.fromisoformat(ts).isocalendar()[1]
    except (TypeError, ValueError):
        return None


def old_policy_ids(recs: list[dict], toks: list[str], today: str) -> list[str]:
    """旧策略: 全 token AND 命中, (-score, index) 排序。与改造前 evaluate
    逐字节等价(_hit 全命中时 fields/spans 同旧值)。"""
    scored = []
    for order, rec in enumerate(recs):
        fields, spans, ht = _hit(_parts(rec), toks)
        if ht == set(toks):
            scored.append((-_score(rec, fields, spans, toks, today), order, rec["id"]))
    scored.sort()
    return [rid for _, _, rid in scored]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".", help="kb 库根(含 kb/index.jsonl)")
    ap.add_argument("--traces", default="traces", help="trace 语料目录")
    ap.add_argument("--week", type=int, default=None, help="ISO 周号(启用达标判据)")
    ap.add_argument("--week-target", type=float, default=0.50, help="达标线, 默认 0.50")
    args = ap.parse_args()

    repo, traces = Path(args.repo), Path(args.traces)
    if not traces.exists():
        print(f"缺语料目录: {traces}", file=sys.stderr)
        sys.exit(2)
    recs = load_index(repo)
    today = dt.date.today().isoformat()

    searches = [s for s in effective(denoise(load_searches(traces), [])[0]) if s.get("query")]
    if not searches:
        print("无语料: traces 里没有有效 search 事件", file=sys.stderr)
        sys.exit(2)

    regressions: list[tuple[str, list[str], list[str]]] = []
    old_hit = new_hit = 0
    week_total = week_hit = 0
    seen: set[str] = set()
    for s in searches:
        q = s["query"]
        toks = q.lower().split()
        if not toks:
            continue
        old_ids = old_policy_ids(recs, toks, today)
        new_ids = [r["id"] for r in evaluate(repo, query=q)[0]]
        if old_ids:
            old_hit += 1
            if old_ids != new_ids:            # 判据 1: 原命中查询结果与排序逐字节不变
                regressions.append((q, old_ids, new_ids))
        if new_ids:
            new_hit += 1
        wk = iso_week(s.get("ts", ""))
        if wk is not None and wk == args.week:
            week_total += 1
            week_hit += bool(new_ids)

    n = len(searches)
    print(f"有效查询 {n} 条 | 旧 hit_rate {old_hit / n:.1%} → 新 hit_rate {new_hit / n:.1%}")
    if args.week:
        if not week_total:
            print(f"W{args.week} 无有效查询样本, 达标判据无法评估")
            return 2
        rate = week_hit / week_total
        ok = rate >= args.week_target
        print(f"W{args.week}: {week_hit}/{week_total} = {rate:.1%}"
              f"（目标 ≥{args.week_target:.0%}）→ {'PASS' if ok else 'FAIL'}")
        if not ok:                                   # 判据 2 未达标即 FAIL, 不能只打印
            return 1
    if regressions:
        print(f"回退 {len(regressions)} 条(旧命中但新结果/排序变了):")
        for q, old, new in regressions[:10]:
            print(f"  {q!r}: {old} -> {new}")
        return 1
    print("判据 1 PASS: 旧命中查询结果集与排序 100% 不变")
    return 0


if __name__ == "__main__":
    sys.exit(main())
