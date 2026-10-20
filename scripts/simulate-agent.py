"""沙箱 Agent 调用仿真 — 生成结构真实的 trace 数据集, 供面板/回放/B-3 调参快速验证。

红线: 只写 --out 指定的仓外隔离目录, 永不碰真实 traces/(git 权威账本)。
事件形状对齐 schema=2 真链路(kb search / kb_get / MCP ext 三类来源)。

用法:
  python scripts/simulate-agent.py --out $env:TEMP\\kb-sim --days 7 [--seed 42]
  kb serve --repo $env:TEMP\\kb-sim --port 4321     # 面板看沙箱数据
  kb trace report --repo $env:TEMP\\kb-sim          # 零命中周报试跑
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import uuid
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCHEMA = 2

# caller 画像: (权重, source, 每活跃时段事件数均值, ext 概率, 零命中概率)
CALLERS = {
    "tencentdb-agent-memory": (0.45, "mcp", 7.0, 0.35, 0.22),
    "agent-kb": (0.35, "cli", 4.0, 0.0, 0.18),
    "flysee-video-web": (0.20, "mcp", 2.5, 0.0, 0.30),
}

# 真实存在的检索词(命中态) 与 库里没有的词(零命中态) —— 后者进周报榜属预期
HIT_WORDS = ["vite", "hmr", "sse", "windows", "计划任务", "令牌", "索引", "上传",
             "容器", "路由", "登录", "代理", "vitest", "分片", "热重载", "沙箱",
             "定时", "回放", "面板", "埋点", "trace", "sse"]
ZERO_WORDS = ["kafka 重平衡", "grpc 流控", "postgres vacuum", "redis 集群脑裂",
              "webhook 签名", "oauth 设备码", "crd 控制器", "opa 策略",
              "envoy 熔断", "clickhouse 物化视图", "websocket 心跳", "tls 轮换"]

TDBM_PAGES = ["redis-ops-runbook", "wiki-architecture", "ingest-pipeline-design",
              "memory-ttl-policy", "wiki-service-api"]


def load_ids() -> list[dict]:
    """真实条目的 id/scope/confidence, 让 matched/returned 的 id 可跳转可回放。"""
    ids = []
    for idx in (REPO / "kb" / "index.jsonl", REPO / "docs" / "kb" / "index.jsonl"):
        if idx.exists():
            for ln in idx.read_text(encoding="utf-8").splitlines():
                if ln.strip():
                    e = json.loads(ln)
                    ids.append({"id": e["id"], "title": e.get("title", ""),
                                "scope": e.get("scope", "stack"),
                                "confidence": e.get("confidence", "probable")})
    if not ids:
        raise SystemExit("index.jsonl 为空, 先 kb index")
    return ids


def _ts(day: dt.date, minute: int) -> str:
    return (dt.datetime(day.year, day.month, day.day)
            + dt.timedelta(minutes=minute)).isoformat(timespec="seconds")


def _poisson(lam: float, rng: random.Random) -> int:
    l, k, p = 2.718281828 ** -lam, 0, 1.0
    while True:
        p *= rng.random()
        if p <= l:
            return k
        k += 1


def gen_search(rng: random.Random, day: dt.date, minute: int, caller: str,
               source: str, ids: list[dict], ext_p: float,
               zero_p: float) -> tuple[dict, int]:
    zero = rng.random() < zero_p
    layers = []
    if zero:
        query = rng.choice(ZERO_WORDS)
        n = rng.randint(1, 2)
        for i, ly in enumerate(["docs", "agent-kb"][:n]):
            layers.append({"repo": ly, "scanned": rng.randint(80, 220),
                           "rejected": {"filter": rng.randint(0, 6),
                                        "query": rng.randint(150, 220)},
                           "matched": [], "taken": 0, "truncated_at_limit": False})
        returned: list[str] = []
        returned_chars = rng.randint(180, 260)
    else:
        query = rng.choice(HIT_WORDS)
        pool = rng.sample(ids, min(len(ids), rng.randint(2, 9)))
        matched, score = [], 6.0 + rng.random() * 2
        for rank, e in enumerate(pool, 1):
            matched.append({"id": e["id"], "title": e["title"], "scope": e["scope"],
                            "confidence": e["confidence"],
                            "hit_fields": rng.sample(["title", "summary", "tags"],
                                                     rng.randint(1, 2)),
                            "hit_spans": [[0, 4]], "score": round(score, 4),
                            "rank": rank})
            score -= rng.uniform(0.3, 1.4)
        limit = rng.choice([10, 10, 10, 5])  # MCP 现默认 10; 5 模拟 CLI 显式收紧
        taken = matched[:limit]
        returned = [m["id"] for m in taken]
        layers.append({"repo": rng.choice(["docs", "agent-kb"]),
                       "scanned": rng.randint(150, 230),
                       "rejected": {"filter": rng.randint(0, 8),
                                    "query": rng.randint(100, 200)},
                       "matched": matched, "taken": len(taken),
                       "truncated_at_limit": len(matched) > limit})
        returned_chars = rng.randint(600, 2400)
    ev = {"kind": "search", "trace_id": f"t-{day:%Y%m%d}-{uuid.uuid4().hex[:4]}",
          "ts": _ts(day, minute), "source": source, "caller_repo": caller,
          "query": query,
          "filters": {"type": None, "domain": None, "tag": None, "scope": None,
                      "status": None, "confidence": None},
          "limit": 10, "duration_ms": rng.randint(3, 45),
          "layers": layers, "returned": returned,
          "returned_chars": returned_chars}
    if ext_p and rng.random() < ext_p:
        hits = [f"source://tdbm/wiki/{rng.choice(TDBM_PAGES)}.md"
                for _ in range(rng.randint(1, 2))]
        ok = rng.random() > 0.08
        ev["ext"] = [{"source": "tdbm", "ok": ok,
                      "error": None if ok else "connect timeout (1.0s)",
                      "hits": hits if ok else []}]
        if ok:
            returned += hits
    return ev, len(returned)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True, help="仓外隔离沙箱根目录")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    if Path(a.out).resolve() == REPO:
        raise SystemExit("--out 不能是仓根")
    if (Path(a.out) / "traces").exists() and list(
            (Path(a.out) / "traces").glob("*.jsonl")):
        raise SystemExit(f"{a.out}/traces 已有数据, 换个目录或先清空(拒绝混写)")

    rng = random.Random(a.seed)
    ids = load_ids()
    out = Path(a.out) / "traces"
    out.mkdir(parents=True, exist_ok=True)
    per_day: dict[dt.date, list[dict]] = defaultdict(list)
    today = dt.date.today()
    n_get = n_search = 0
    for d in range(a.days - 1, -1, -1):
        day = today - dt.timedelta(days=d)
        weekend = day.weekday() >= 5
        names = list(CALLERS)
        weights = [CALLERS[c][0] for c in names]
        minute = 9 * 60 + rng.randint(0, 30)
        while minute < 19 * 60:
            minute += int(rng.expovariate(1 / rng.uniform(20, 90)))
            if rng.random() > (0.35 if weekend else 0.8):
                continue
            caller = rng.choices(names, weights)[0]
            _, source, lam, ext_p, zero_p = CALLERS[caller]
            for _ in range(max(1, _poisson(lam / 4, rng))):
                ev, nhits = gen_search(rng, day, minute, caller, source, ids,
                                       ext_p, zero_p)
                per_day[day].append(ev)
                n_search += 1
                # search→get 链接: 有命中的检索 60% 触发 1-2 次全文读取
                if nhits and rng.random() < 0.6:
                    w = [1.0 / (i + 1) for i in range(len(ev["returned"]))]  # 排名偏置点击
                    for _ in range(rng.randint(1, min(2, nhits))):
                        got = rng.choices(ev["returned"], w)[0]
                        g = {"kind": "get", "trace_id": ev["trace_id"],
                             "ts": _ts(day, minute + rng.randint(0, 9)),
                             "source": source, "caller_repo": caller, "id": got,
                             "layer": "source:tdbm" if got.startswith("source://")
                             else rng.choice(["docs", "agent-kb"]),
                             "ok": True, "chars": rng.randint(800, 6000)}
                        per_day[day].append(g)
                        n_get += 1
    total = 0
    for day, events in sorted(per_day.items()):
        events.sort(key=lambda e: e["ts"])
        lines = [json.dumps({"kind": "meta", "schema": SCHEMA}, ensure_ascii=False)]
        lines += [json.dumps(e, ensure_ascii=False) for e in events]
        (out / f"{day:%Y-%m-%d}.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8")
        total += len(events)
    print(f"沙箱: {a.out}\n{a.days} 天 {n_search} search / {n_get} get, "
          f"共 {total} 事件 → {out}")


if __name__ == "__main__":
    main()
