from __future__ import annotations
from pathlib import Path
from kb.entry import parse_entry, dump_entry


def _find(repo_root: Path, id: str) -> Path | None:
    for p in sorted((Path(repo_root) / "kb").rglob("*.md")):
        if parse_entry(p).fm.get("id") == id:
            return p
    return None


def promote(repo_root: Path, id: str, to: str) -> dict:
    path = _find(repo_root, id)
    if not path:
        raise FileNotFoundError(f"entry not found: {id}")
    e = parse_entry(path)
    e.fm["scope"] = to
    tags = list(e.fm.get("tags", []) or [])
    if "promoted" not in tags:
        tags.append("promoted")
    e.fm["tags"] = tags
    path.write_text(dump_entry(e), encoding="utf-8")
    return e.fm
