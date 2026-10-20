from __future__ import annotations
import datetime as dt
import json
import re
from pathlib import Path
from kb.dedup import fingerprint_source, fingerprint_text
from kb.entry import Entry, parse_entry, dump_entry
from kb.new_entry import create_entry
from kb.taxonomy import load_taxonomy


class GateViolation(Exception):
    """门控拒绝: 试图做 Agent 不允许的写操作."""


class DuplicateCandidate(Exception):
    def __init__(self, entries: list[dict]):
        self.entries = entries
        super().__init__("duplicate candidates: "
                         + ", ".join(str(e.get("id")) for e in entries))


def _title_tokens(title: str) -> list[str]:
    toks = [t for t in re.split(r"[^0-9a-z\u4e00-\u9fff]+", title.lower()) if len(t) >= 2]
    return toks[:3]


def _index_records(repo: Path) -> list[dict]:
    jl = repo / "kb" / "index.jsonl"
    if not jl.exists():
        return []
    return [json.loads(x) for x in jl.read_text(encoding="utf-8").splitlines() if x.strip()]


def _tmp_entry(body: str) -> Entry:
    return Entry(fm={}, body=body, path=Path("<pending>"))


def _dup_hits(repos: list[Path], fp: str, title: str) -> list[dict]:
    hits: list[dict] = []
    seen: set[str] = set()
    toks = _title_tokens(title)
    for rp in repos:
        for r in _index_records(rp):
            rid = r.get("id")
            if rid in seen:
                continue
            hit = bool(fp) and r.get("dedup_key") == fp
            if not hit:
                hay = (r.get("title") or "").lower()
                hit = any(t in hay for t in toks)
            if hit:
                hits.append({**r, "layer": rp.name})
                seen.add(rid)
    return hits


def create_draft(repo, *, type: str, domain: str, title: str, body: str | None = None,
                 tags: list[str] | None = None, severity: str | None = None,
                 agent_kbs: tuple = (), today: dt.date | None = None) -> Entry:
    """Agent 唯一写入口: 强制 draft/speculative/project + 查重拒建."""
    today = today or dt.date.today()
    repos = [Path(repo)] + [Path(p) for p in agent_kbs]
    fp = ""
    if body:
        # fingerprint_text 内含短源门槛(规范化后 <16 返回 ""), 单次提取+哈希
        fp = fingerprint_text(fingerprint_source(_tmp_entry(body)))
    hits = _dup_hits(repos, fp, title)
    if hits:
        raise DuplicateCandidate(hits)
    e = create_entry(Path(repo), type=type, domain=domain, scope="project",
                     title=title, generated=True, today=today)
    if body or tags or severity:
        cur = parse_entry(e.path)
        if body:
            cur.body = f"\n# {title}\n\n{body.strip()}\n"
        if tags:
            cur.fm["tags"] = list(tags)
        if severity:
            cur.fm["severity"] = severity
        e.path.write_text(dump_entry(cur), encoding="utf-8")
        e = parse_entry(e.path)
    return e


_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"proposed", "accepted", "deprecated"},
    "proposed": {"draft", "accepted", "deprecated"},
    "accepted": {"deprecated", "superseded"},
    "deprecated": set(),
    "superseded": set(),
}


def _find(repo, id: str) -> Path:
    kb = Path(repo) / "kb"
    for p in sorted(kb.rglob("*.md")) if kb.exists() else []:
        if p.name in ("INDEX.md",):
            continue
        if parse_entry(p).fm.get("id") == id:
            return p
    raise FileNotFoundError(f"entry not found: {id}")


def _save(p: Path, fm: dict, body: str, today: dt.date) -> Entry:
    fm["updated"] = today.isoformat()
    p.write_text(dump_entry(Entry(fm=fm, body=body, path=p)), encoding="utf-8")
    return parse_entry(p)


def update_draft(repo, id: str, *, title: str | None = None, body: str | None = None,
                 tags: list[str] | None = None, severity: str | None = None,
                 today: dt.date | None = None) -> Entry:
    """人工 CLI: 仅 draft 可编辑正文/元数据."""
    p = _find(repo, id)
    e = parse_entry(p)
    if e.fm.get("status") != "draft":
        raise GateViolation(f"{id}: only draft entries are editable, current status={e.fm.get('status')}")
    fm = dict(e.fm)
    cur_body = e.body
    h1 = e.h1() or fm.get("title", "")
    if title:
        fm["title"] = title
        cur_body = cur_body.replace(f"# {h1}", f"# {title}", 1)
    if body:
        cur_body = f"\n# {fm.get('title', h1)}\n\n{body.strip()}\n"
    if tags is not None:
        fm["tags"] = list(tags)
    if severity:
        fm["severity"] = severity
    return _save(p, fm, cur_body, today or dt.date.today())


def review(repo, id: str, to: str, today: dt.date | None = None, *,
           by: str | None = None, confidence: str | None = None,
           evidence: str | None = None) -> Entry:
    """状态流转, 按 _TRANSITIONS; accepted 拒绝 speculative。

    by="agent" 为自审: accepted 时写 verified_by=agent + auto-reviewed 标签 +
    verification 留痕(供事后抽查回滚)。confidence 仅随 accepted 提升生效。
    人工流转带 evidence 时同样写 verification 留痕, 但不打自审标记。
    """
    p = _find(repo, id)
    e = parse_entry(p)
    fm = dict(e.fm)
    if to == "accepted" and confidence in ("verified", "probable"):
        fm["confidence"] = confidence
    frm = e.fm.get("status", "")
    if to not in _TRANSITIONS.get(frm, set()):
        raise GateViolation(f"{id}: illegal transition {frm} -> {to}")
    if to == "accepted" and fm.get("confidence") == "speculative":
        raise GateViolation(f"{id}: confidence=speculative must be verified before accepted")
    fm["status"] = to
    if to == "accepted" and by == "agent":
        fm["verified_by"] = "agent"
        tags = list(fm.get("tags") or [])
        if "auto-reviewed" not in tags:
            tags.append("auto-reviewed")
        fm["tags"] = tags
        d = (today or dt.date.today()).isoformat()
        fm["verification"] = {"evidence": (evidence or "").strip(), "reviewed_at": d}
    elif to == "accepted" and (evidence or "").strip():
        # 人工终审带证据: 同样写 verification 留痕, 但不打 auto-reviewed/verified_by
        d = (today or dt.date.today()).isoformat()
        fm["verification"] = {"evidence": evidence.strip(), "reviewed_at": d}
    return _save(p, fm, e.body, today or dt.date.today())


def set_scope(repo, id: str, scope: str, today: dt.date | None = None) -> Entry:
    """人工 CLI: 设置 scope 并移除 needs-scope-review tag."""
    if scope not in load_taxonomy()["enums"]["scope"]:
        raise ValueError(f"unknown scope: {scope}")
    p = _find(repo, id)
    e = parse_entry(p)
    fm = dict(e.fm)
    fm["scope"] = scope
    fm["tags"] = [t for t in (fm.get("tags") or []) if t != "needs-scope-review"]
    return _save(p, fm, e.body, today or dt.date.today())


def export_entry(project_repo, agent_kb_repo, id: str, *, to_scope: str,
                 today: dt.date | None = None) -> Path:
    """人工 CLI: 将项目库条目搬到 Agent-KB 库(stack/universal), 回填 source.project."""
    if to_scope not in ("stack", "universal"):
        raise ValueError(f"export target scope must be stack/universal, got {to_scope}")
    src = _find(project_repo, id)
    rel = src.relative_to(Path(project_repo) / "kb")
    dst = Path(agent_kb_repo) / "kb" / rel
    if dst.exists():
        raise GateViolation(f"target already exists: {dst}")
    e = parse_entry(src)
    fm = dict(e.fm)
    fm["scope"] = to_scope
    fm["tags"] = [t for t in (fm.get("tags") or []) if t != "needs-scope-review"]
    fm["source"] = {**(fm.get("source") or {}),
                    "project": fm.get("source", {}).get("project") or Path(project_repo).resolve().name}
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(dump_entry(Entry(fm=fm, body=e.body, path=dst)), encoding="utf-8")
    src.unlink()
    return dst
