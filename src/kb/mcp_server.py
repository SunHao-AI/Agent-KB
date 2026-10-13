from __future__ import annotations
import json
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from kb.gate import DuplicateCandidate, GateViolation, create_draft, update_draft
from kb.layers import get_layered, related_layers, search_layers
from kb.query import get_entry


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def build_server(repo: Path, agent_kbs: list[Path] | None = None,
                 repo_name: str | None = None) -> FastMCP:
    repo = Path(repo)
    kbs = [Path(p) for p in (agent_kbs or [])]
    layers = [repo] + kbs
    name = repo_name or repo.resolve().name
    mcp = FastMCP(f"kb-{name}")

    @mcp.tool()
    def kb_search(query: str | None = None, type: str | None = None,
                  domain: str | None = None, tag: str | None = None,
                  scope: str | None = None, limit: int = 10) -> str:
        """检索知识库(项目层优先, 再通用层)。只返回元数据+摘要+路径, 不返回正文。
        draft 条目永不返回。命中后再用 kb_get 读全文。"""
        rows = search_layers(layers, type=type, domain=domain, tag=tag,
                             scope=scope, query=query, limit=limit)
        keep = ("id", "title", "type", "domain", "tags", "scope", "status",
                "severity", "confidence", "path", "summary", "updated", "repo")
        return _json([{k: r.get(k) for k in keep} for r in rows])

    @mcp.tool()
    def kb_get(id: str) -> str:
        """按 id 读取单条全文 markdown。"""
        got = get_layered(layers, id)
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

    return mcp
