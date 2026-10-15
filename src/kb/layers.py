from __future__ import annotations

from pathlib import Path

from kb.query import get_entry, related
from kb.search import evaluate


def _name(repo: Path) -> str:
    # 与 index 写入的 repo 字段同口径(小写规范名), 保证 search 行与 get 层标签一致
    return Path(repo).resolve().name.lower()


def search_layers_report(repos: list[Path], *, type=None, domain=None, tag=None,
                         scope=None, status=None, confidence=None, query=None,
                         limit: int = 10) -> tuple[list[dict], list[dict]]:
    """双层合并检索 + 逐层死因报告(供 trace)。repos 顺序即优先级, 逐层取满即截断。"""
    out: list[dict] = []
    reports: list[dict] = []
    for rp in repos:
        rows, rep = evaluate(rp, type=type, domain=domain, tag=tag, scope=scope,
                             status=status, confidence=confidence, query=query)
        take = max(0, limit - len(out))
        chosen = rows[:take]
        rep.update({"repo": _name(rp), "taken": len(chosen),
                    "truncated_at_limit": len(chosen) < len(rows)})
        reports.append(rep)
        out.extend(chosen)
    return out[:limit], reports


def search_layers(repos: list[Path], *, type=None, domain=None, tag=None, scope=None,
                  status=None, confidence=None, query=None, limit: int = 10) -> list[dict]:
    """双层合并检索: repos 顺序即优先级, 逐层取满即截断(spec §7)。"""
    rows, _ = search_layers_report(repos, type=type, domain=domain, tag=tag, scope=scope,
                                   status=status, confidence=confidence, query=query,
                                   limit=limit)
    return rows


def get_layered(repos: list[Path], id: str) -> tuple[str, str] | None:
    for rp in repos:
        text = get_entry(rp, id)
        if text:
            return text, _name(rp)
    return None


def related_layers(repos: list[Path], id: str) -> list[dict]:
    out, seen = [], set()
    for rp in repos:
        for r in related(rp, id):
            if r["id"] not in seen:
                out.append(r)
                seen.add(r["id"])
    return out
