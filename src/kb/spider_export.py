"""trace → prompt-spider-session/v1 转换器(spec §6)。

纯函数: 只消费 trace dict, 不碰文件。有损映射(扫描线/字段高亮降级为 detail 文字)。
导入报错时只改本文件 RECORD_* 常量区适配, 不动数据层。
"""
from __future__ import annotations

import re

FORMAT = "prompt-spider-session/v1"


def spider_id(native: str) -> str:
    """原生 id → 蜘蛛合法 event.id(对端正则 ^[\\p{L}\\p{N}_.:-]+$, 真机校准:
    source://tdbm/wiki/x.md 的 '/' 会被拒)。search/get 两侧同函数保证 you 匹配。"""
    return re.sub(r"[^\w.:-]", "-", str(native))


ROUTES = {"code": {"label": "项目层命中", "color": "#42D6A4"},
          "model": {"label": "通用层命中", "color": "#F28A76"},
          "ext": {"label": "外接源命中", "color": "#F34A87"},
          "you": {"label": "已读消费", "color": "#F0CA57"}}
_LAYER_ROUTE = {0: "code", 1: "model"}   # reports 顺序: 项目层在前(spec §7)
# 对端 lib/replay.js + lib/config.js 硬限制(真机校准 2026-10-15):
# log 批 1..100 事件; subtitle≤160; duration=末条 at; log≤10万条/16MiB。
_BATCH = 100
_SUBTITLE_MAX = 160
# 时间轴(gif 逐词扫描节奏): 首条 lead 出场, 每条错开 stagger, running→+fly 落定,
# 尾缓冲后 complete。stagger 上限保节奏感、下限防大 n 总时长失控(封顶≈14s);
# 全部挤在同一时刻会让动画 1s 内闪完, 观感=蜘蛛空转(与 preview.gif 的差距根源)。
_T_CONFIG, _T_LEAD, _T_FLY, _T_TAIL = 0.0, 0.5, 0.45, 2.0
_STAGGER_MAX, _STAGGER_MIN, _STAGGER_BUDGET = 0.6, 0.12, 11.0
_ZERO_END = 2.5   # 零命中是静帧展示, 无动画可看, 保持短循环不让人等


def _stagger(n: int) -> float:
    if n <= 1:
        return _STAGGER_MAX
    return max(_STAGGER_MIN, min(_STAGGER_MAX, _STAGGER_BUDGET / (n - 1)))


def _detail(m: dict) -> str:
    # .get: 历史 trace(schema 早期)可能缺 hit_fields/hit_spans, 回放不得因此炸
    fields = "+".join(m.get("hit_fields") or []) or "filter"
    return f"hit: {fields} @ {m.get('hit_spans') or []}"


def _chunks(xs: list) -> list[list]:
    return [xs[i:i + _BATCH] for i in range(0, len(xs), _BATCH)]


def to_record(search_ev: dict, get_evs: list[dict]) -> dict:
    """一条 search trace + 其关联 get 事件 → 可导入的完整 record。

    event.id 一律经 spider_id 归一(原生 id 可含 '/' 等对端非法字符);
    consumed 仍回原生 id(仓内语义), 仅 record 内做映射。
    """
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
            # .get: 手工构造/早期 schema trace 可缺 title → 回退 id(缺 title 曾致 replay/spider KeyError 掐连接)
            events.append({"id": spider_id(m["id"]),
                           "label": (m.get("title") or "")[:40] or m["id"],
                           "route": final, "status": "completed",
                           "detail": _detail(m)})
    for e in search_ev.get("ext", []) or []:  # 外接源命中 → ext 分支(不在 layers 内)
        for eid in e.get("hits", []):
            if eid not in returned:
                continue
            final = "you" if eid in read_ids else "ext"
            events.append({"id": spider_id(eid), "label": f"外接 {e.get('source')}: {eid}"[:40],
                           "route": final, "status": "completed",
                           "detail": f"source://{e.get('source')}"})
    consumed = {g["id"] for g in get_evs
                if g.get("trace_id") == search_ev["trace_id"] and g["id"] in returned}
    events.sort(key=lambda e: (e["route"] != "code", e["route"] != "model",
                               e["route"] != "ext", e["id"]))
    layers_note = " · ".join(
        # .get: rejected 子键可缺(手工/早期 schema), 回放不得因此炸
        f"{l['repo']} 扫描{l.get('scanned', '?')} 过滤-{(l.get('rejected') or {}).get('filter', 0)}"
        f" 词-{(l.get('rejected') or {}).get('query', 0)}"
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
        # wall: 词墙布局(参考演示同款观感——事件铺成中部词墙、蜘蛛轨道压在词上)。
        # 依赖克隆仓 layout 白名单含 wall(lib/config.js, 2026-10-21 已加),
        # 否则 normalizeConfig 拒导入——回放目标就是该克隆仓, 版本需同步。
        "layout": "wall", "unit": "task", "routes": ROUTES,
    }
    # 对端契约: log 项用 type; configure/events/complete; events 批 1..100;
    # revision 严格递增, at 非递减且≤duration; 空批非法; log≤10万条。
    log = [{"revision": 1, "at": _T_CONFIG, "type": "configure", "config": config}]
    entries: list[tuple[float, int, list]] = []  # (at, 同刻序, events 批)
    if events:
        # you(已读)无扫描动画语义, 随首批一起落定; 其余逐条: running→(+fly)completed。
        # stagger<fly 时下一条 running 比上一条 completed 先到, 必须按 at 排序后再编
        # revision(直接顺序产 log 会 at 倒退, 被对端 validateRecord 拒收)。
        running = [e for e in events if e["route"] != "you"]
        you_first = [dict(e, status="completed") for e in events if e["route"] == "you"]
        if running:
            stag = _stagger(len(running))
            you_head, you_rest = you_first[:_BATCH - 1], you_first[_BATCH - 1:]
            for i, e in enumerate(running):
                t_r = round(_T_LEAD + i * stag, 2)
                pend = you_head if i == 0 else []
                entries.append((t_r, 0, pend + [dict(e, status="running")]))
                entries.append((round(t_r + _T_FLY, 2), 1, [dict(e, status="completed")]))
            t_last = round(_T_LEAD + (len(running) - 1) * stag + _T_FLY, 2)
            for batch in _chunks(you_rest):  # you 溢出(>99)单独成批, at 与末条同刻
                entries.append((t_last, 1, batch))
            end = round(t_last + _T_TAIL, 2)
        else:  # 全 you(只读未扫): 无动画可排, 一批落定+短循环
            for batch in _chunks(you_first):
                entries.append((_T_LEAD, 0, batch))
            end = _ZERO_END
    else:
        end = _ZERO_END
    entries.sort(key=lambda x: (x[0], x[1]))
    rev = 1
    for at, _, batch in entries:
        rev += 1
        log.append({"revision": rev, "at": at, "type": "events", "events": batch})
    rev += 1
    log.append({"revision": rev, "at": end, "type": "complete",
                "status": "completed"})
    return {"format": FORMAT, "version": 1, "id": search_ev["trace_id"],
            "status": "completed", "duration": end,
            "initialConfig": config, "config": config,
            "events": events, "log": log,
            "consumed": sorted(consumed)}
