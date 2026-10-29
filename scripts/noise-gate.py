"""检索面噪音门槛 — spec 2026-10-29 §6.5 的可复现实现。

判据口径(均为 **agent 实际消费面**, 不是全库命中口径):
  1) top-N 结果中 `hit_fields` 仅含 sections 的位次占比 ≤ --max-sections-share(默认 20%)
  2) 前 N 名被挤出的位次数 ≤ 新挤入的位次数(需 --against 提供基线生成物)

为什么不用"全库仅-sections 命中占比": 该项把"内容从完全不可见变为可见"也计为噪音,
而召回扩大正是检索面扩面的目的。2026-10-29 首版门槛(30% 全库口径)据此会把一次
净收益改动判为 FAIL, 详见 spec §5.1。

语料默认取 traces/*.jsonl 里的真实历史 query(agent 真实查询词, 非人工构造)。

用法:
  python scripts/noise-gate.py                                    # 主仓, 仅判据 1
  python scripts/noise-gate.py --repo ..\\flysee_video_web\\docs   # 业务仓
  python scripts/noise-gate.py --against HEAD~2                    # 加判据 2(基线=改动前生成物)

退出码: 0=PASS; 1=FAIL(任一判据不满足); 2=输入不可用(缺生成物/无语料)。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from kb.search import _hit, _parts, _score  # noqa: E402


def load_index(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]


def load_queries(traces: Path) -> list[str]:
    out: list[str] = []
    for f in sorted(traces.glob("*.jsonl")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            try:
                rec = json.loads(ln)
            except json.JSONDecodeError:
                continue
            if rec.get("kind") == "search" and rec.get("query"):
                out.append(rec["query"])
    return list(dict.fromkeys(out))


def baseline_index(repo: Path, ref: str) -> list[dict]:
    """从 git ref 读基线生成物(不动工作区)。repo 是 kb 库根, 生成物在其 kb/ 子目录。"""
    root = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=repo,
                          capture_output=True, text=True).stdout.strip()
    rel = (repo.resolve() / "kb" / "index.jsonl").relative_to(Path(root).resolve()).as_posix()
    r = subprocess.run(["git", "show", f"{ref}:{rel}"], cwd=repo,
                       capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        sys.exit(f"git show {ref}:{rel} 失败: {r.stderr.strip()[:120]}")
    return [json.loads(x) for x in r.stdout.splitlines() if x.strip()]


def ranked(recs: list[dict], toks: list[str], today: str) -> list[tuple[str, list[str]]]:
    scored = []
    for order, rec in enumerate(recs):
        fields, spans = _hit(_parts(rec), toks)
        if fields:
            scored.append((-_score(rec, fields, spans, toks, today), order,
                           rec["id"], fields))
    scored.sort()
    return [(rid, fields) for _, _, rid, fields in scored]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo", default=".", help="kb 库根(含 kb/index.jsonl), 默认当前目录")
    ap.add_argument("--traces", default="traces", help="历史 query 语料目录")
    ap.add_argument("--against", default=None, help="基线生成物所在 git ref(启用判据 2)")
    ap.add_argument("--limit", type=int, default=5, help="agent 消费面宽度 N, 默认 5")
    ap.add_argument("--max-sections-share", type=float, default=0.20,
                    help="判据 1 阈值, 默认 0.20")
    a = ap.parse_args()

    repo, traces = Path(a.repo).resolve(), Path(a.traces).resolve()
    cur_path = repo / "kb" / "index.jsonl"
    if not cur_path.exists():
        print(f"缺生成物: {cur_path}", file=sys.stderr)
        return 2
    if not traces.is_dir():
        print(f"缺语料目录: {traces}", file=sys.stderr)
        return 2

    cur = load_index(cur_path)
    queries = load_queries(traces)
    if not queries:
        print("语料里没有 search 记录", file=sys.stderr)
        return 2
    today = dt.date.today().isoformat()

    slots = sections_only = 0
    for q in queries:
        toks = q.lower().split()
        if not toks:
            continue
        for _, fields in ranked(cur, toks, today)[:a.limit]:
            slots += 1
            sections_only += fields == ["sections"]
    share = sections_only / max(slots, 1)
    p1 = share <= a.max_sections_share
    print(f"query 数                     : {len(queries)}")
    print(f"判据1 前{a.limit} 仅-sections 位次   : {sections_only}/{slots} = {share:.1%} "
          f"(阈值 ≤{a.max_sections_share:.0%}) → {'PASS' if p1 else 'FAIL'}")

    ok = p1
    if a.against:
        base = baseline_index(repo, a.against)
        pushed = gained = 0
        for q in queries:
            toks = q.lower().split()
            if not toks:
                continue
            old_ids = [i for i, _ in ranked(base, toks, today)[:a.limit]]
            new_ids = [i for i, _ in ranked(cur, toks, today)[:a.limit]]
            pushed += len(set(old_ids) - set(new_ids))
            gained += len(set(new_ids) - set(old_ids))
        p2 = pushed <= gained
        ok = ok and p2
        print(f"判据2 前{a.limit} 挤出 / 挤入 位次数 : {pushed} / {gained} "
              f"(阈值 挤出 ≤ 挤入) → {'PASS' if p2 else 'FAIL'}")
        print(f"零命中 query  base → cur    : "
              f"{sum(1 for q in queries if q.lower().split() and not ranked(base, q.lower().split(), today))}"
              f" → {sum(1 for q in queries if q.lower().split() and not ranked(cur, q.lower().split(), today))}")
    print(f"\n结论: {'PASS — 检索面改动可保留' if ok else 'FAIL — 按 spec §7 回退 sections 面'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
