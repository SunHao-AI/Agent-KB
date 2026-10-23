from __future__ import annotations

import json
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from kb import trace as kbtrace
from kb import sources
from kb.gate import (DuplicateCandidate, GateViolation, create_draft, review,
                     update_draft)
from kb.layers import get_layered, related_layers, search_layers_report

AUTO_ACCEPT_CAP = 3  # 单次会话(每 server 实例) agent 自审 accepted 上限


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def _compact(obj) -> str:
    """FR-4.1: 检索返回走 compact 序列化(-20% 体积); 低频写路径仍用 _json。"""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def build_server(repo: Path, agent_kbs: list[Path] | None = None,
                 repo_name: str | None = None) -> FastMCP:
    repo = Path(repo)
    kbs = [Path(p) for p in (agent_kbs or [])]
    layers = [repo] + kbs
    name = repo_name or repo.resolve().name.lower()
    connectors = sources.build_connectors()  # FR-6: 默认空(纯本地), KB_SOURCES 开启
    mcp = FastMCP(f"kb-{name}")
    auto_accepted = 0  # 本会话已自审 accepted 计数

    @mcp.tool()
    def kb_search(query: str | None = None, type: str | None = None,
                  domain: str | None = None, tag: str | None = None,
                  scope: str | None = None, limit: int = 10) -> str:
        """检索知识库(项目层优先, 再通用层, 再外接源)。只返回元数据+摘要+路径, 不返回正文。
        draft 条目永不返回。命中后再用 kb_get 读全文。
        检索语义: 查询按空白分词, 每词须命中 title/tags/keywords/summary(AND);
        keywords 为正文派生词(报错串/函数名/配置键可直接搜)。中文连写自动按
        2-gram 覆盖率匹配, 但仍建议 2-4 字短词。命中按相关性排序(hit_fields
        说明命中在哪个字段)。
        外接源命中 id 形如 source://<源>/<原生id>(source 字段标来源), 同样用 kb_get 读。
        零命中返回 {"hits": [], "hint": 死因计数, "suggest": 近似词} —— hint 区分
        "库内没有/被过滤/词太长", 按 suggest 改写重试, 不要直接断定库里没有。"""
        t0 = time.perf_counter()
        try:
            limit = int(limit)  # 非数值回退默认(§51 同族); 零/负值不抬成 1, 见下
        except (TypeError, ValueError):
            limit = 10
        if limit <= 0:  # 零名额: 不扫库不触外接源, 如实告知(旧实现扫全库后
            out = _compact({"hits": [],  # 产出"死于过滤器 0/词匹配 0"的自相矛盾
                            "hint": f"limit={limit} 名额为零, 未执行检索; "
                                    "请用正整数 limit 重试",
                            "suggest": []})
            if kbtrace.trace_enabled():
                kbtrace.append_event(kbtrace.build_search_event(
                    trace_id=kbtrace.new_trace_id(), source="mcp", caller_repo=name,
                    query=query, filters={"type": type, "domain": domain, "tag": tag,
                                           "scope": scope, "status": None,
                                           "confidence": None},
                    limit=limit, reports=[], returned=[],
                    duration_ms=round((time.perf_counter() - t0) * 1000),
                    returned_chars=len(out)))
            return out
        rows, reports = search_layers_report(
            layers, type=type, domain=domain, tag=tag, scope=scope, query=query, limit=limit)
        # FR-6.1 联邦: 外接源摘要先行补位(预算=剩余名额), 任何源故障静默跳过
        ext_rows: list[dict] = []
        ext_health: list[dict] = []
        if query and connectors:
            remain = max(0, limit - len(rows))
            for c in connectors:
                if remain <= 0:
                    break
                hits = c.search(query, limit=remain)
                remain -= len(hits)
                ext_rows.extend(dict(h, hit_fields=["source"], hit_spans=[]) for h in hits)
                ext_health.append(c.health())
        rows = rows + ext_rows
        if rows or not query:
            payload = rows if not ext_health else {"rows": rows, "sources": ext_health}
            out = _compact(payload)
        else:  # FR-3.2: 零命中从裸 [] 升级为死因+建议(命中态结构不变)
            scanned = sum(r.get("scanned", 0) for r in reports)
            n_f = sum(r.get("rejected", {}).get("filter", 0) for r in reports)
            n_q = sum(r.get("rejected", {}).get("query", 0) for r in reports)
            suggest = next((r["suggest"] for r in reports if r.get("suggest")), [])
            out = _compact({"hits": [],
                            "hint": (f"scanned {scanned}: 死于过滤器 {n_f}, "
                                     f"死于词匹配 {n_q}; 建议用更短单 token 重试"),
                            "suggest": suggest,
                            "sources": ext_health or None})
        if kbtrace.trace_enabled():
            ev = kbtrace.build_search_event(
                trace_id=kbtrace.new_trace_id(), source="mcp", caller_repo=name,
                query=query, filters={"type": type, "domain": domain, "tag": tag,
                                      "scope": scope, "status": None, "confidence": None},
                limit=limit, reports=reports, returned=[r["id"] for r in rows],
                duration_ms=round((time.perf_counter() - t0) * 1000),
                returned_chars=len(out))
            if ext_health:  # FR-6.1: 外接源命中进同一 trace, 蜘蛛/矩阵才能按源分层
                ev["ext"] = [{"source": h.get("source"),
                              "ok": h.get("ok"), "error": h.get("error"),
                              "hits": [r["id"] for r in rows
                                       if r.get("id", "").startswith(
                                           f"source://{h.get('source')}/")]}
                             for h in ext_health]
            kbtrace.append_event(ev)
        return out

    @mcp.tool()
    def kb_get(id: str) -> str:
        """按 id 读取单条全文 markdown(外接源 id 形如 source://<源>/<原生id>)。"""
        got = None
        if id.startswith("source://"):
            for c in connectors:
                text = c.get(id)
                if text is not None:
                    got = (text, f"source:{c.name}")
                    break
        else:
            got = get_layered(layers, id)
        if kbtrace.trace_enabled():
            # entry_id=id: 优先关联到返回过该条目的 search(§40 消费漏计修复);
            # 外接源 id(source://…)不在本地 returned 里, 自然回退纯最近一次
            kbtrace.append_event(kbtrace.build_get_event(
                trace_id=kbtrace.latest_search_id(name, entry_id=id),
                source="mcp", caller_repo=name,
                id=id, layer=got[1] if got else None, ok=got is not None,
                chars=len(got[0]) if got else None))
        if got is None:
            raise ValueError(f"not found: {id}")
        return got[0]

    @mcp.tool()
    def kb_related(id: str) -> str:
        """读取某条目的关联/被引用条目(双层, 只回元数据+摘要)。"""
        return _json(related_layers(layers, id))

    @mcp.tool()
    def kb_create(type: str, domain: str, title: str, body: str,
                  tags: list[str] | None = None, severity: str | None = None) -> str:
        """沉淀新知识。强制 status=draft / confidence=speculative / scope=project。
        查重命中会失败并返回候选 id, 此时应改用 kb_update。单次仅允许 1 条。"""
        try:
            e = create_draft(repo, type=type, domain=domain, title=title,
                             body=body, tags=tags, severity=severity,
                             agent_kbs=tuple(kbs))
        except DuplicateCandidate as exc:
            raise ValueError("duplicate candidates: "
                             + _json([{"id": h.get("id"), "title": h.get("title")}
                                      for h in exc.entries])
                             + " — use kb_update instead") from None
        return _json({**e.fm, "path": str(e.path)})

    @mcp.tool()
    def kb_update(id: str, title: str | None = None, body: str | None = None,
                  tags: list[str] | None = None, severity: str | None = None) -> str:
        """更新**本项目 draft 条目**。accepted/proposed 一律拒绝(人工 CLI 专用)。"""
        try:
            e = update_draft(repo, id, title=title, body=body, tags=tags, severity=severity)
        except FileNotFoundError:
            raise ValueError(f"not found in project layer: {id}") from None
        return _json({**e.fm, "path": str(e.path)})

    @mcp.tool()
    def kb_review(id: str, to: str, confidence: str | None = None,
                  evidence: str | None = None) -> str:
        """自主终审本项目条目(状态流转: draft→proposed→accepted / deprecated)。

        规则: 流转必须沿合法路径(draft→accepted 或 proposed→accepted);
        accepted 必须带实测 evidence 并把 confidence 提升为 verified/probable,
        否则被拒(speculative 不可 accepted)。自审 accepted 会打 auto-reviewed
        留痕, 单会话最多 3 条。scope 上提(stack/universal)仍只能人工 CLI。"""
        nonlocal auto_accepted
        try:
            if to == "accepted":
                if not (evidence and evidence.strip()):
                    raise GateViolation(
                        f"{id}: accepted 需先完成自行验证并附 evidence"
                        f"(当前 confidence=speculative 不可 accepted)")
                if auto_accepted >= AUTO_ACCEPT_CAP:
                    raise GateViolation(
                        f"{id}: 单次会话自主终审已达上限 {AUTO_ACCEPT_CAP} 条")
            e = review(repo, id, to, by="agent", confidence=confidence,
                       evidence=evidence)
        except GateViolation as exc:
            raise ValueError(str(exc)) from None
        except FileNotFoundError:
            raise ValueError(f"not found in project layer: {id}") from None
        if to == "accepted":
            auto_accepted += 1
        return _json({**e.fm, "path": str(e.path)})

    return mcp
