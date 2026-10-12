from __future__ import annotations
from collections import Counter
from pathlib import Path
import jsonschema
from kb.entry import parse_entry
from kb.taxonomy import load_taxonomy, derive_schema


# `kb index` 的生成物固定名, 不作为知识条目参与 lint
_GENERATED_NAMES = {"INDEX.md", "index.jsonl", "index.draft.jsonl"}


def _iter_entries(root: Path):
    kb = Path(root) / "kb"
    if not kb.exists():
        return
    # 只遍历 kb 根第一层条目目录(kb/<type>/)再向下 rglob, 不进入 kb 根下
    # 挂载的子仓/子树(如 .agent-kb/), 避免扫入子仓生成物造成误报
    for d in sorted(p for p in kb.iterdir() if p.is_dir() and not p.name.startswith(".")):
        for p in sorted(d.rglob("*.md")):
            if p.name in _GENERATED_NAMES:
                continue
            yield parse_entry(p)


def lint_repo(repo_root: Path, scope: str = "project") -> list[str]:
    tax = load_taxonomy()
    schema = derive_schema(tax)
    validator = jsonschema.Draft202012Validator(schema)
    errors: list[str] = []
    entries = list(_iter_entries(repo_root))
    ids = {e.fm.get("id") for e in entries}
    id_counts = Counter(e.fm.get("id") for e in entries if e.fm.get("id"))
    for e in entries:
        rid = e.fm.get("id", e.path.name)
        if id_counts.get(e.fm.get("id"), 0) > 1:
            errors.append(f"{rid}: duplicate id {e.fm['id']}")
        for err in sorted(validator.iter_errors(e.fm), key=lambda x: x.json_path):
            errors.append(f"{rid}: schema {err.json_path}: {err.message}")
        if e.fm.get("scope") == "project" and scope == "agent-kb":
            errors.append(f"{rid}: scope=project must not live in agent-kb")
        if e.fm.get("scope") != "project" and scope == "project":
            errors.append(f"{rid}: scope!=project must be promoted to agent-kb")
        for f in ("related",):
            for ref in e.fm.get(f, []) or []:
                if ref not in ids:
                    errors.append(f"{rid}: {f} references missing {ref}")
        for f in ("supersedes", "superseded_by"):
            ref = e.fm.get(f)
            if ref and ref not in ids:
                errors.append(f"{rid}: {f} references missing {ref}")
        h1 = sum(1 for ln in e.body.splitlines() if ln.strip().startswith("# "))
        if h1 != 1:
            errors.append(f"{rid}: expected exactly one H1, found {h1}")
    return errors
