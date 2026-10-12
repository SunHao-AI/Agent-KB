from __future__ import annotations
import datetime as dt
import re
import secrets
from pathlib import Path
from kb.taxonomy import load_taxonomy
from kb.entry import Entry, parse_entry

_NONKEBAB = re.compile(r"[^a-z0-9]+")


def new_id(today: dt.date) -> str:
    return f"kb-{today.strftime('%Y%m%d')}-{secrets.token_hex(2)}"


def slug(title: str, today: dt.date) -> str:
    k = _NONKEBAB.sub("-", title.lower()).strip("-")
    return f"{today.isoformat()}-{k}" if k else today.isoformat()


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
    fm_text = "\n".join(f"{k}: {v}" for k, v in fm.items())
    body = f"\n# {title}\n\n{_template_body(type)}"
    rel = Path("kb") / type / domain / f"{slug(title, today)}.md"
    path = Path(repo_root) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"---\n{fm_text}\n---\n{body}", encoding="utf-8")
    return parse_entry(path)
