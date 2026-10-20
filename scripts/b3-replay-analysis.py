"""B-3 调参试跑(沙箱重放): limit 10→5 安全性 + rank 消费分布。
注意: 仿真数据的 get 选择是随机的, 结论仅验证方法流程, 不构成真实调参依据。"""
import json, sys
from pathlib import Path
from collections import Counter

traces = sorted(Path(sys.argv[1], "traces").glob("*.jsonl"))
searches, gets = [], []
for f in traces:
    lines = f.read_text(encoding="utf-8").splitlines()
    for ln in lines[1:]:
        ev = json.loads(ln)
        (searches if ev["kind"] == "search" else gets).append(ev)

by_tid = {s["trace_id"]: s for s in searches}
limit10 = [s for s in searches if s["returned"] and s["limit"] == 10]
truncated = [s for s in limit10 if any(l["truncated_at_limit"] for l in s["layers"])]
print(f"search={len(searches)} 有返回且limit10={len(limit10)} 其中截断={len(truncated)}")

# gets 落在被截断部分的概率: 若某 trace 的 get id 不在 returned(10) 里 → limit5 也影响不到它,
# 但若 get id 在 returned 的 6-10 位 → limit=5 后该 get 不会发生(检索方看不到该条)
rank_c, lost_by_5 = Counter(), 0
get_by_tid = {}
for g in gets:
    get_by_tid.setdefault(g["trace_id"], []).append(g["id"])
for tid, gids in get_by_tid.items():
    s = by_tid.get(tid)
    if not s:
        continue
    ret = s["returned"]
    for gid in gids:
        if gid in ret:
            rank_c[ret.index(gid) + 1] += 1
            if ret.index(gid) + 1 > 5:
                lost_by_5 += 1
print("消费落在 returned 第几位:", dict(sorted(rank_c.items())))
print(f"limit 10→5 会丢失的消费: {lost_by_5}/{sum(rank_c.values())}")

# 截断但未消费榜外: limit=5 后有多少 trace 的 matched>5 却没有任何 get(榜外条目本就无人看)
no_get_over5 = sum(1 for s in truncated
                   if s["trace_id"] not in get_by_tid
                   and sum(l["taken"] for l in s["layers"]) > 5)
print(f"截断且完全无消费的 trace(榜外6-10位无人问津): {no_get_over5}/{len(truncated)}")
