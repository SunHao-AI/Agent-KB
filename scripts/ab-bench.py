"""A/B 基准对比 — 两个代码变体在同机交替跑同一负载, 出可信中位数。

本机噪声实测可达 7× (同一段未改动代码写侧 911~6695ms), 单次对比不可信。
本脚本用两条纪律消除噪声:
  1) 交替轮次 base→opt→base→opt … 消除时间漂移(不用"先跑完 A 再跑完 B");
  2) 每个变体在**独立子进程 + 独立 sys.path** 跑, 并断言 kb.__file__ 落在预期树,
     防止 editable 安装(kb 指向 src/)导致两个变体其实测了同一份代码。

基线树用 git worktree 检出(不动工作区), 跑完自动清理。

用法:
  python scripts/ab-bench.py --against HEAD              # 当前改动 vs HEAD
  python scripts/ab-bench.py --against v0.1.0 --rounds 5
  python scripts/ab-bench.py --against HEAD --mode single  # 单线程写(真实形态)
  python scripts/ab-bench.py --against HEAD --mode both

mode: concurrent=16线程强竞争 | single=单线程(各进程各写, 生产常态) | both
退出码: 0=跑通(结论见输出); 1=变体解析异常或子进程失败。
"""
from __future__ import annotations

import argparse
import json
import shutil
import statistics
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

CHILD = textwrap.dedent("""
    import json, shutil, statistics, sys, time
    src, mode, out = sys.argv[1], sys.argv[2], sys.argv[3]
    sys.path.insert(0, src)
    from pathlib import Path
    import kb
    want = Path(src).resolve()
    got = Path(kb.__file__).resolve().parent.parent
    assert got == want, f"WRONG PACKAGE: kb from {got}, expected {want}"
    from kb import trace as t

    root = Path(sys.argv[4])
    shutil.rmtree(root, ignore_errors=True)
    t.traces_dir(root).mkdir(parents=True)
    ev = {'kind': 'search', 'trace_id': 'x', 'ts': '2026-10-20T12:00:00+08:00',
          'source': 'cli', 'caller_repo': 'c', 'query': 'q' * 32, 'filters': {},
          'limit': 10, 'duration_ms': 1, 'layers': [], 'returned': [], 'returned_chars': 0}

    if mode == 'single':
        for i in range(80):                      # 预热(冷启动/文件缓存)
            ev['trace_id'] = f'w{i}'
            t.append_event(ev, root, ingest=False)
        ts = []
        for i in range(300):
            ev['trace_id'] = f's{i}'
            t0 = time.perf_counter()
            t.append_event(ev, root, ingest=False)
            ts.append(time.perf_counter() - t0)
        ts.sort()
        n = len(ts)
        res = {'p50_ms': round(ts[n // 2] * 1000, 3),
               'p95_ms': round(ts[int(n * .95)] * 1000, 3),
               'mean_ms': round(statistics.mean(ts) * 1000, 3)}
    else:
        from concurrent.futures import ThreadPoolExecutor
        def w(a):
            for i in range(125):
                e = dict(ev, trace_id=f'{a[0]}-{i}', caller_repo=f'c{a[0]}')
                t.append_event(e, root, ingest=False)
        t0 = time.perf_counter()
        with ThreadPoolExecutor(16) as ex:
            list(ex.map(w, [(i,) for i in range(16)]))
        el = (time.perf_counter() - t0) * 1000
        lines = [l for f in sorted(t.traces_dir(root).glob('*.jsonl'))
                 for l in f.read_text(encoding='utf-8').splitlines() if l.strip()]
        ok = bad = 0
        for l in lines:
            try:
                json.loads(l); ok += 1
            except Exception:
                bad += 1
        res = {'total_ms': round(el), 'lines': len(lines), 'parseable': ok, 'corrupt': bad}

    json.dump(res, open(out, 'w'))
""")


def run_child(py: str, src: str, mode: str, work: Path, tag: str) -> dict | None:
    out = work / f"{tag}.json"
    script = work / "_ab_child.py"
    script.write_text(CHILD, encoding="utf-8")
    p = subprocess.run([py, str(script), src, mode, str(out), str(work / f"data_{tag}")],
                       capture_output=True, text=True)
    if p.returncode:
        print(f"    ! {tag} 子进程失败: {(p.stderr or p.stdout).strip()[-260:]}")
        return None
    return json.load(open(out, encoding="utf-8"))


def med(rows: list[dict], key: str) -> float:
    return statistics.median(r[key] for r in rows)


def main() -> int:
    ap = argparse.ArgumentParser(description="两个代码变体的交替 A/B 基准")
    ap.add_argument("--against", required=True, help="基线 git ref(如 HEAD / v0.1.0 / 分支名)")
    ap.add_argument("--rounds", type=int, default=4, help="交替轮数(默认 4)")
    ap.add_argument("--mode", choices=["concurrent", "single", "both"], default="both")
    ap.add_argument("--work", default=None, help="临时目录(默认 <系统temp>/kb-ab)")
    ap.add_argument("--json", dest="json_out", default=None)
    a = ap.parse_args()

    work = Path(a.work or Path(tempfile.gettempdir()) / "kb-ab")
    work.mkdir(parents=True, exist_ok=True)
    base_wt = work / "base-tree"
    shutil.rmtree(base_wt, ignore_errors=True)

    print(f"检出基线 {a.against} → {base_wt}")
    r = subprocess.run(["git", "-C", str(REPO), "worktree", "add", str(base_wt),
                        a.against, "--detach"], capture_output=True, text=True)
    if r.returncode:
        print(f"git worktree add 失败: {r.stderr.strip()[-300:]}", file=sys.stderr)
        return 1
    variants = [("base", str(base_wt / "src")), ("opt", str(REPO / "src"))]
    modes = ["concurrent", "single"] if a.mode == "both" else [a.mode]
    res: dict = {}
    rc = 0
    try:
        for mode in modes:
            print(f"\n== mode={mode} ==")
            acc = {n: [] for n, _ in variants}
            for rnd in range(a.rounds):  # 交替轮次, 消除时间漂移
                for name, src in variants:
                    row = run_child(sys.executable, src, mode, work, f"{mode}_{name}_{rnd}")
                    if row is None:
                        rc = 1
                        continue
                    acc[name].append(row)
                    extra = (f" 落盘={row.get('lines')}/{row.get('parseable', 0) + row.get('corrupt', 0)}"
                             f" 碎行={row.get('corrupt')}") if mode == "concurrent" else ""
                    key = "total_ms" if mode == "concurrent" else "p50_ms"
                    print(f"  r{rnd} {name:5s} {row[key]:9.3f}{'' if mode == 'concurrent' else 'ms'}{extra}")
            summary = {}
            for name, rows in acc.items():
                if not rows:
                    rc = 1
                    continue
                key = "total_ms" if mode == "concurrent" else "p50_ms"
                vals = sorted(r[key] for r in rows)
                summary[name] = {"median": round(med(rows, key), 3), "all": vals,
                                 "corrupt_total": sum(r.get("corrupt", 0) for r in rows),
                                 "lost_total": sum(2001 - r["lines"] for r in rows)
                                 if mode == "concurrent" else 0}
            if {"base", "opt"} <= summary.keys():
                b, o = summary["base"], summary["opt"]
                ratio = round(b["median"] / o["median"], 2) if o["median"] else 0
                unit = "ms" if mode == "single" else "ms(总)"
                trend = "opt 更快" if ratio > 1 else ("基本持平" if ratio == 1 else "opt 更慢")
                print(f"  → median base={b['median']}{unit} opt={o['median']}{unit} "
                      f"(base/opt={ratio}× → {trend})")
                if mode == "concurrent":
                    print(f"    基线 丢行={b['lost_total']} 碎行={b['corrupt_total']} | "
                          f"优化 丢行={o['lost_total']} 碎行={o['corrupt_total']}")
                    if o["corrupt_total"] or o["lost_total"]:
                        print("    ✗ 优化版仍有数据丢失/碎行 — 不可接受")
                        rc = 1
                    elif b["lost_total"] or b["corrupt_total"]:
                        print("    ✓ 优化版修复了基线的并发丢行(耗时代价见上)")
            res[mode] = summary
    finally:
        subprocess.run(["git", "-C", str(REPO), "worktree", "remove", str(base_wt), "--force"],
                       capture_output=True)
        if not a.json_out:
            shutil.rmtree(work, ignore_errors=True)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(f"\n结果: {Path(a.json_out).resolve()}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
