from __future__ import annotations
import json
from pathlib import Path


def _load(repo_root: Path):
    jl = Path(repo_root) / "kb" / "index.jsonl"
    if not jl.exists():
        return []
    return [json.loads(x) for x in jl.read_text(encoding="utf-8").splitlines() if x.strip()]


def search(repo_root: Path, type=None, domain=None, tag=None, scope=None,
           status=None, confidence=None, query=None, limit: int = 20) -> list[dict]:
    recs = _load(repo_root)
    out = []
    q = query.lower() if query else None
    for r in recs:
        if type and r["type"] != type:
            continue
        if domain and domain not in r["domain"]:
            continue
        if tag and tag not in r.get("tags", []):
            continue
        if scope and r["scope"] != scope:
            continue
        if status and r["status"] != status:
            continue
        if confidence and r["confidence"] != confidence:
            continue
        if q:
            hay = f"{r['title']} {' '.join(r.get('tags', []))} {r['summary']}".lower()
            if q not in hay:
                continue
        out.append(r)
    return out[:limit]
