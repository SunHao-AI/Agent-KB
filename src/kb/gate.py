from __future__ import annotations
import datetime as dt
import json
import re
from pathlib import Path
from kb.dedup import fingerprint, fingerprint_source, normalize
from kb.entry import Entry, parse_entry, dump_entry
from kb.new_entry import create_entry

_MIN_FP_LEN = 16


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
        src = normalize(fingerprint_source(_tmp_entry(body)))
        fp = fingerprint(_tmp_entry(body)) if len(src) >= _MIN_FP_LEN else ""
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
