from __future__ import annotations
from pathlib import Path
from kb.query import get_entry, related
from kb.search import search


def _name(repo: Path) -> str:
    return Path(repo).resolve().name


def search_layers(repos: list[Path], *, type=None, domain=None, tag=None, scope=None,
                  status=None, confidence=None, query=None, limit: int = 10) -> list[dict]:
    """双层合并检索: repos 顺序即优先级, 逐层取满即截断(spec §7)."""
    out: list[dict] = []
    for rp in repos:
        if len(out) >= limit:
            break
        rows = search(rp, type=type, domain=domain, tag=tag, scope=scope,
                      status=status, confidence=confidence, query=query,
                      limit=limit - len(out))
        out.extend(rows)
    return out[:limit]


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
