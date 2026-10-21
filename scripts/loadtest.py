"""负载/压力测试 — 检索核心 + 聚合层 + HTTP 并发 + 写侧完整性, 一键出对比表。

红线: 只在 --work 指定的仓外隔离目录合成数据, 永不读写真实 traces/(git 权威账本)。
完整性断言(不丢行/不碎行/边写边读不脏读)失败即退 1, 可直接当回归门禁。

场景:
  A 检索核心   search.evaluate(真实仓 或 合成索引; 中英 mixed / 零命中)
  B 聚合层     read_traces / aggregate / feed_events / callers / zero_hit_board
  C HTTP 并发  serve(ThreadingHTTPServer) 各路由冷热延迟 + 缓存加速比
  C2 一致性    append 后 /api/stats 计数必须立即增长(AggCache 不得脏读)
  D 写侧并发   多线程 append_event → 行数/可解析/trace_id 唯一

用法:
  python scripts/loadtest.py                       # 全场景, 合成数据
  python scripts/loadtest.py --repo . --only A     # 用真实索引只跑检索
  python scripts/loadtest.py --scale 3             # 数据量 ×3
  python scripts/loadtest.py --json r.json         # 另存机器可读结果
  python scripts/loadtest.py --work D:\\tmp\\lt    # 指定临时目录(默认系统 temp)

退出码: 0=全部通过; 1=完整性断言失败; 2=环境/参数问题。
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import socket
import statistics
import sys
import tempfile
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _p in (str(REPO / "src"),):  # 免安装直跑; 已安装时 editable 安装同样生效
    if _p not in sys.path:
        sys.path.insert(0, _p)

from kb import search, serve, stats  # noqa: E402
from kb import trace as kbtrace  # noqa: E402

QUERIES = ["vite hmr", "sqlite 锁", "sse 断线", "容器 时区", "windows 路径", "tls 轮换"]
WORDS = "caseSensitive import.meta.hot identity autouse"


def pct(ts: list[float]) -> dict[str, float]:
    ts = sorted(ts)
    return {"p50": round(ts[len(ts) // 2], 2),
            "p95": round(ts[int(len(ts) * .95)], 2),
            "mean": round(statistics.mean(ts), 2)}


def timeit(fn, n: int, warmup: int = 3) -> dict:
    for _ in range(warmup):
        fn()
    ts = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        ts.append((time.perf_counter() - t0) * 1000)
    return pct(ts)


def synth_index(root: Path, n: int) -> None:
    """合成 index.jsonl(形状对齐真索引, 确定性生成), 供检索核心压测。"""
    (root / "kb").mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(n):
        rows.append(json.dumps({
            "id": f"kb-202610{i % 100:02d}-{i:04x}",
            "title": f"vite hmr 失效排查 {i} {WORDS}",
            "tags": ["vite", "hmr", f"t{i % 37}"],
            "keywords": [f"key{i % 91}", "import.meta.hot"],
            "summary": "热更新在 windows 大小写混用路径下静默失效, 需统一 fs.caseSensitive"
                       + " 补充" * 20,
            "type": "pitfall", "domain": ["frontend"], "scope": "stack",
            "status": "accepted", "confidence": "verified",
            "created": "2026-09-01", "updated": "2026-10-01"}, ensure_ascii=False))
    (root / "kb" / "index.jsonl").write_text("\n".join(rows), encoding="utf-8")


def synth_traces(root: Path, n_search: int, n_get: int, days: int, seed: int) -> None:
    """合成按日分片的 trace(事件形状对齐 schema=2), 供聚合/HTTP/写侧压测。"""
    rnd = random.Random(seed)
    d = kbtrace.traces_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    callers = [f"proj-{i}" for i in range(6)]
    by_day: dict[str, list[dict]] = {}
    for i in range(n_search):
        day = f"2026-10-{i % days + 1:02d}"
        by_day.setdefault(day, []).append({
            "kind": "search", "trace_id": f"t-{i:08d}", "ts": f"{day}T10:00:{i % 60:02d}+08:00",
            "source": rnd.choice(["cli", "mcp"]), "caller_repo": rnd.choice(callers),
            "query": rnd.choice(QUERIES), "filters": {}, "limit": 10,
            "duration_ms": rnd.randint(3, 45),
            "layers": [{"repo": "docs", "scanned": 120,
                        "rejected": {"query": 100, "filter": 15},
                        "matched": [{"id": f"kb-x{j}", "title": "标题" * 15,
                                     "hit_fields": ["title"]} for j in range(3)],
                        "taken": 3, "truncated_at_limit": False}],
            "returned": [f"kb-x{j}" for j in range(3)], "returned_chars": 900})
    for i in range(n_get):
        day = f"2026-10-{i % days + 1:02d}"
        by_day.setdefault(day, []).append({
            "kind": "get", "trace_id": f"t-{rnd.randrange(n_search):08d}",
            "ts": f"{day}T11:00:{i % 60:02d}+08:00", "source": "mcp",
            "caller_repo": rnd.choice(callers), "id": f"kb-x{i % 18}",
            "layer": "docs", "ok": True, "chars": 4000})
    for day, evs in sorted(by_day.items()):
        with (d / f"{day}.jsonl").open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({"kind": "meta", "schema": kbtrace.SCHEMA}) + "\n")
            fh.writelines(json.dumps(e, ensure_ascii=False) + "\n" for e in evs)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------- 场景 ----
# (场景名, query)。CJK 多 token 未命中会逐条走 2-gram 覆盖, 是最贵路径 —
# 命中/未命中的延迟差是真实成本特征, 各行的 scanned/matched 会打印出来。
SEARCH_CASES = [("英文 token", "vite hmr"),
                ("中文长句", "热更新 大小写 混用 路径 静默"),
                ("零命中(2-gram 兜底最贵)", "zzqq 不存在词组")]
REAL_QUERY = "vite"  # 在真实仓有命中(勿改成命中不了的词; 换仓时用 --only A 前先验证)


def scenario_search(repo: Path, big: Path, n_synth: int, out: dict) -> None:
    print("== A 检索核心 search.evaluate(线性扫全表是设计选择, 此为回归基线非缺陷) ==")
    rows = [(f"合成 {n_synth} 条 / {name}", big, q) for name, q in SEARCH_CASES]
    if repo and (repo / "kb" / "index.jsonl").exists():
        rows.insert(0, (f"真实仓 {repo.name}", repo, REAL_QUERY))
    for label, root, q in rows:
        hits, report = search.evaluate(root, query=q)
        r = out.setdefault("A", {})[label] = timeit(lambda: search.evaluate(root, query=q), 30)
        r["scanned"] = report.get("scanned")
        r["matched"] = len(hits)
        if not r["scanned"]:  # 索引没加载到 = 这行数据无意义, 直接判失败
            print(f"  {label:34s} ✗ scanned=0 (index.jsonl 未加载?)")
            r["error"] = "index not loaded"
            continue
        print(f"  {label:34s} p50={r['p50']:8.2f}ms p95={r['p95']:8.2f}ms "
              f"scanned={r['scanned']} matched={r['matched']}")


def scenario_agg(root: Path, out: dict) -> None:
    print("== B 聚合层 ==")
    s, g, _ = kbtrace.read_traces(root=root)
    print(f"  数据: {len(s)} search / {len(g)} get")
    cases = [("read_traces", lambda: kbtrace.read_traces(root=root)),
             ("aggregate", lambda: stats.aggregate(s, g)),
             ("feed_events", lambda: stats.feed_events(s, g, limit=50)),
             ("callers", lambda: stats.callers(s)),
             ("zero_hit_board", lambda: stats.zero_hit_board(s)),
             ("top_consumed", lambda: stats.top_consumed(s, g)),
             ("find_trace", lambda: kbtrace.find_trace(s[0]["trace_id"], root=root))]
    for label, fn in cases:
        r = out.setdefault("B", {})[label] = timeit(fn, 8, warmup=1)
        print(f"  {label:16s} p50={r['p50']:9.1f}ms p95={r['p95']:9.1f}ms")


def scenario_http(root: Path, port: int, out: dict, fails: list[str]) -> None:
    print(f"== C HTTP 并发 (serve :{port}, ThreadingHTTPServer) ==")
    print("   注: cold=本进程内该路由首次命中; 若同次运行先跑了 B, trace 解析缓存已热, "
          "cold 只反映 AggCache 冷。冷进程实测 /api/stats≈5.4s。")
    srv = serve.ServeServer(("127.0.0.1", port), root, None, None, quiet=True)
    th = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    th.start()
    time.sleep(0.3)
    try:
        base = f"http://127.0.0.1:{port}"

        def hit(path: str) -> float:
            t0 = time.perf_counter()
            with urllib.request.urlopen(base + path, timeout=120) as r:
                r.read()
            return (time.perf_counter() - t0) * 1000

        # 延迟表先跑: /api/stats 的 cold 必须是"进程内首次命中", 若先跑 C2 会被预热,
        # cold 数字就失去意义(实测 cold 9ms vs 真 cold 5389ms)。
        for path, conc, n in (("/healthz", 10, 100),
                              ("/api/stats?caller=*", 10, 20),
                              ("/api/feed?caller=*&limit=30", 10, 60),
                              ("/api/callers", 10, 30),
                              (f"/api/replay/{s0(root)}", 4, 12)):
            cold = hit(path)
            lat = [hit(path) for _ in range(n)]  # 同 key 重复 = 面板轮询形态
            p = pct(lat)
            speed = round(cold / p["p50"], 1) if p["p50"] else 0
            with ThreadPoolExecutor(conc) as ex:  # 并发墙钟
                t0 = time.perf_counter()
                list(ex.map(lambda _: hit(path), range(conc)))
                wall = round(time.perf_counter() - t0, 2)
            out.setdefault("C", {})[path] = {"cold_ms": round(cold, 1), **p,
                                             "speedup": speed, "conc_wall_s": wall}
            print(f"  {path[:34]:36s} cold={cold:8.1f}ms warm_p50={p['p50']:7.1f}ms "
                  f"×{speed:6.1f} conc{conc}_wall={wall}s")

        # C2 一致性(放最后, 它会往库里 append 并使缓存失效):
        # append 后 stats 计数必须立即增长 — AggCache 按 trace 签名失效, 不得脏读。
        def n_searches() -> int:
            with urllib.request.urlopen(base + "/api/stats?caller=*", timeout=120) as r:
                return json.load(r)["kpi"]["searches"]

        before, grew = n_searches(), 0
        for i in range(5):
            kbtrace.append_event({"kind": "search", "trace_id": f"live-{i}",
                                  "ts": "2026-10-28T12:00:00+08:00", "source": "cli",
                                  "caller_repo": "live", "query": "q", "filters": {},
                                  "limit": 10, "duration_ms": 1, "layers": [],
                                  "returned": ["a"], "returned_chars": 10}, root, ingest=False)
            after = n_searches()
            grew += int(after > before)
            before = after
        c2 = grew == 5
        out["C2_write_then_read"] = {"ok": c2, "grew": f"{grew}/5"}
        print(f"  C2 边写边读不脏读: {'PASS' if c2 else 'FAIL(缓存读到旧数据)'} ({grew}/5)")
        if not c2:
            fails.append("C2 聚合缓存脏读: append 后 /api/stats 未反映新事件")
    finally:
        srv.shutdown()


def s0(root: Path) -> str:
    s, _, _ = kbtrace.read_traces(root=root)
    return s[0]["trace_id"]


def scenario_write(work: Path, out: dict, fails: list[str], threads: int, per: int) -> None:
    print(f"== D 写侧完整性 ({threads} 线程 × {per} 事件) ==")
    root = work / "writer"
    shutil.rmtree(root, ignore_errors=True)
    kbtrace.traces_dir(root).mkdir(parents=True, exist_ok=True)
    total = threads * per

    def w(tid: int) -> None:
        for i in range(per):
            kbtrace.append_event({"kind": "search", "trace_id": f"w{tid}-{i}",
                                  "ts": "2026-10-20T12:00:00+08:00", "source": "cli",
                                  "caller_repo": f"c{tid}", "query": "q" * 32, "filters": {},
                                  "limit": 10, "duration_ms": 1, "layers": [],
                                  "returned": [], "returned_chars": 0}, root, ingest=False)

    t0 = time.perf_counter()
    with ThreadPoolExecutor(threads) as ex:
        list(ex.map(w, range(threads)))
    dt_ms = (time.perf_counter() - t0) * 1000

    lines = [ln for f in sorted(kbtrace.traces_dir(root).glob("*.jsonl"))
             for ln in f.read_text(encoding="utf-8").splitlines() if ln.strip()]
    ok, bad, ids = 0, 0, []
    for ln in lines:
        try:
            ev = json.loads(ln)
            ok += 1
            if ev.get("kind") == "search":
                ids.append(ev.get("trace_id"))
        except json.JSONDecodeError:
            bad += 1
    meta = 0
    for ln in lines:
        try:
            if json.loads(ln).get("kind") == "meta":
                meta += 1
        except json.JSONDecodeError:
            pass
    dup = len(ids) - len(set(ids))
    lost = total - len(ids)
    r = out["D"] = {"total_ms": round(dt_ms), "ms_per_event": round(dt_ms / total, 3),
                    "expected": total, "written": len(ids), "lost": lost,
                    "corrupt": bad, "meta_lines": meta, "dup": dup}
    print(f"  {dt_ms:.0f}ms ({r['ms_per_event']}ms/事件) 落盘={len(ids)}/{total} "
          f"丢行={lost} 碎行={bad} 重复={dup} meta={meta}")
    if bad:
        fails.append(f"D 碎行 {bad} 条: 并发 append 写出不可解析行")
    if lost:
        fails.append(f"D 丢行 {lost} 条: 并发 append 事件未落盘(数据丢失)")
    if dup:
        fails.append(f"D 重复 trace_id {dup} 条")


def main() -> int:
    ap = argparse.ArgumentParser(description="Agent-KB 负载/压力测试(仓外隔离, 不碰真实 traces)")
    ap.add_argument("--repo", default=None, help="可选: 用该仓真实 index.jsonl 跑检索场景")
    ap.add_argument("--work", default=None, help="临时工作目录(默认 <系统temp>/kb-loadtest)")
    ap.add_argument("--scale", type=float, default=1.0, help="合成数据规模倍数(默认 1)")
    ap.add_argument("--threads", type=int, default=16, help="写侧并发线程数(默认 16)")
    ap.add_argument("--port", type=int, default=0, help="HTTP 端口(默认自动选空闲端口)")
    ap.add_argument("--only", default="ABC D", help="限定场景, 如 A / AB / ABCD(默认全部)")
    ap.add_argument("--json", dest="json_out", default=None, help="结果另存 JSON 路径")
    ap.add_argument("--keep", action="store_true", help="保留临时目录(便于排查)")
    a = ap.parse_args()
    only = a.only.replace(" ", "").upper()
    scale = max(0.1, a.scale)

    work = Path(a.work or Path(tempfile.gettempdir()) / "kb-loadtest")
    work.mkdir(parents=True, exist_ok=True)
    repo = Path(a.repo).resolve() if a.repo else REPO
    out: dict = {"scale": scale, "work": str(work)}
    fails: list[str] = []
    n_search = int(20000 * scale)
    print(f"工作目录: {work}   规模 ×{scale}(≈{n_search} search 事件)\n")

    big = work / "bigrepo"
    n_synth = int(2400 * scale)
    if "A" in only:
        shutil.rmtree(big, ignore_errors=True)
        synth_index(big, n_synth)
        scenario_search(repo, big, n_synth, out)
        for label, r in out.get("A", {}).items():
            if r.get("error"):
                fails.append(f"A {label}: {r['error']}")

    bigt = work / "bigraph"
    if "B" in only or "C" in only:
        shutil.rmtree(bigt, ignore_errors=True)
        synth_traces(bigt, n_search, int(1500 * scale), 28, seed=42)
        scenario_agg(bigt, out)
    if "C" in only:
        port = a.port or free_port()
        try:
            scenario_http(bigt, port, out, fails)
        except OSError as e:
            print(f"  [环境] HTTP 场景跳过: {e}", file=sys.stderr)
            return 2
    if "D" in only:
        scenario_write(work, out, fails, a.threads, 125)

    print("\n---- 结论 ----")
    if fails:
        for f in fails:
            print(f"  ✗ {f}")
        print(f"  完整性断言失败 {len(fails)} 项")
    else:
        print("  ✓ 完整性断言全部通过(无丢行/碎行/脏读)")
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(out, indent=1, ensure_ascii=False),
                                    encoding="utf-8")
        print(f"  结果: {Path(a.json_out).resolve()}")
    if not a.keep:
        shutil.rmtree(work, ignore_errors=True)
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
