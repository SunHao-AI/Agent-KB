from __future__ import annotations
import datetime as dt
import re
import secrets
from pathlib import Path
import yaml
from kb.taxonomy import load_taxonomy
from kb.entry import Entry, parse_entry

_NONKEBAB = re.compile(r"[^a-z0-9]+")


def new_id(today: dt.date) -> str:
    return f"kb-{today.strftime('%Y%m%d')}-{secrets.token_hex(2)}"


def slug(title: str, today: dt.date) -> str:
    k = _NONKEBAB.sub("-", title.lower()).strip("-")
    return f"{today.isoformat()}-{k}" if k else today.isoformat()


def _unique_path(repo_root: Path, type_name: str, domain: str,
                 title: str, today: dt.date, entry_id: str) -> Path:
    base = slug(title, today)
    # kebab 部分为空(如纯中文标题)时用 id 后 4 hex 兜底, 避免同日同目录路径相同
    if base == today.isoformat():
        base = f"{base}-{entry_id[-4:]}"
    path = Path(repo_root) / "kb" / type_name / domain / f"{base}.md"
    n = 2
    while path.exists():
        path = path.with_name(f"{base}-{n}.md")
        n += 1
    return path


def _template_body(type_name: str) -> str:
    tax = load_taxonomy()
    sections = tax["types"][type_name]["sections"]
    return "\n".join(f"## {s}\n<!-- TODO -->\n" for s in sections)


def create_entry(repo_root: Path, type: str, domain: str, scope: str,
                 title: str, generated: bool, today: dt.date) -> Entry:
    tax = load_taxonomy()
    if type not in tax["types"]:
        raise ValueError(f"unknown type: {type}")
    if domain not in tax["domains"]:
        raise ValueError(f"unknown domain: {domain}")
    fm = {
        "id": new_id(today),
        "title": title,
        "type": type,
        "domain": [domain],
        "tags": [],
        "scope": scope,
        "status": "draft" if generated else "proposed",
        "confidence": "speculative" if generated else "probable",
        "created": today.isoformat(),
        "updated": today.isoformat(),
    }
    if "severity" in tax["types"][type].get("requires", []):
        fm["severity"] = "medium"
    fm_text = yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).strip()
    body = f"\n# {title}\n\n{_template_body(type)}"
    path = _unique_path(Path(repo_root), type, domain, title, today, fm["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm_text}\n---\n{body}", encoding="utf-8")
    return parse_entry(path)
