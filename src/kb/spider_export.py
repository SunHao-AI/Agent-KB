"""trace → prompt-spider-session/v1 转换器(spec §6)。

纯函数: 只消费 trace dict, 不碰文件。有损映射(扫描线/字段高亮降级为 detail 文字)。
导入报错时只改本文件 RECORD_* 常量区适配, 不动数据层。
"""
from __future__ import annotations

FORMAT = "prompt-spider-session/v1"
ROUTES = {"code": {"label": "项目层命中", "color": "#42D6A4"},
          "model": {"label": "通用层命中", "color": "#F28A76"},
          "you": {"label": "已读消费", "color": "#F0CA57"}}
_LAYER_ROUTE = {0: "code", 1: "model"}   # reports 顺序: 项目层在前(spec §7)
# 对端 lib/replay.js + lib/config.js 硬限制(真机校准 2026-10-15):
# log 批 1..100 事件; subtitle≤160; duration=末条 at。
_BATCH = 100
_SUBTITLE_MAX = 160
_T_CONFIG, _T_RUNNING, _T_DONE, _T_END = 0.0, 0.5, 1.5, 2.5


def _detail(m: dict) -> str:
    fields = "+".join(m["hit_fields"]) or "filter"
    return f"hit: {fields} @ {m['hit_spans']}"


def _chunks(xs: list) -> list[list]:
    return [xs[i:i + _BATCH] for i in range(0, len(xs), _BATCH)]


def to_record(search_ev: dict, get_evs: list[dict]) -> dict:
    """一条 search trace + 其关联 get 事件 → 可导入的完整 record。"""
    read_ids = {g["id"] for g in get_evs if g.get("trace_id") == search_ev["trace_id"]}
    ts = str(search_ev.get("ts", ""))[:10]
    returned = set(search_ev.get("returned", []))
    events: list[dict] = []
    for idx, layer in enumerate(search_ev.get("layers", [])):
        route = _LAYER_ROUTE.get(idx, "model")
        for m in layer["matched"]:
            if m["id"] not in returned:
                continue
            final = "you" if m["id"] in read_ids else route
            events.append({"id": m["id"], "label": m["title"][:40] or m["id"],
                           "route": final, "status": "completed",
                           "detail": _detail(m)})
    consumed = {e["id"] for e in events if e["route"] == "you"}
    events.sort(key=lambda e: (e["route"] != "code", e["route"] != "model", e["id"]))
    layers_note = " · ".join(
        f"{l['repo']} 扫描{l['scanned']} 过滤-{l['rejected']['filter']} 词-{l['rejected']['query']}"
        for l in search_ev.get("layers", []))
    truncated = next((l["repo"] for l in search_ev.get("layers", [])
                      if l.get("truncated_at_limit")), None)
    n = len(events)
    config = {
        "title": f"KB 命中回放 {search_ev['trace_id']}"[:80],
        "subtitle": ((f"query: {search_ev.get('query') or '-'} | {layers_note} | "
                      f"limit={search_ev.get('limit')}"
                      + (f" | 截断于{truncated}层" if truncated else "")
                      + (" | 0 命中" if n == 0 else ""))[:_SUBTITLE_MAX]),
        "modelName": f"{search_ev.get('caller_repo', '?')} · {ts}"[:80],
        "layout": "landscape", "unit": "task", "routes": ROUTES,
    }
    # 对端契约: log 项用 type; configure/events/complete; events 批 1..100;
    # revision 严格递增, at 非递减; 空批非法。
    log = [{"revision": 1, "at": _T_CONFIG, "type": "configure", "config": config}]
    rev = 1
    if events:
        running = [dict(e, status="running") for e in events if e["route"] != "you"]
        for batch in _chunks(running):
            rev += 1
            log.append({"revision": rev, "at": _T_RUNNING, "type": "events",
                        "events": batch})
        for batch in _chunks(events):
            rev += 1
            log.append({"revision": rev, "at": _T_DONE, "type": "events",
                        "events": [dict(e, status="completed") for e in batch]})
    rev += 1
    log.append({"revision": rev, "at": _T_END, "type": "complete",
                "status": "completed"})
    return {"format": FORMAT, "version": 1, "id": search_ev["trace_id"],
            "status": "completed", "duration": _T_END,
            "initialConfig": config, "config": config,
            "events": events, "log": log,
            "consumed": sorted(consumed)}
