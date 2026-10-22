from __future__ import annotations
import json
import datetime as dt
from collections import Counter
from pathlib import Path
from kb.entry import parse_entry


def _records(repo_root: Path):
    jl = Path(repo_root) / "kb" / "index.jsonl"
    dj = Path(repo_root) / "kb" / "index.draft.jsonl"
    recs = []
    for f in (jl, dj):
        if f.exists():
            recs += [json.loads(x) for x in f.read_text(encoding="utf-8").splitlines() if x.strip()]
    return recs


def _find_path(repo_root: Path, id: str) -> Path | None:
    for r in _records(repo_root):
        if r["id"] == id:
            return Path(repo_root) / r["path"]
    return None


def get_entry(repo_root: Path, id: str) -> str | None:
    p = _find_path(repo_root, id)
    return p.read_text(encoding="utf-8") if p else None


def related(repo_root: Path, id: str) -> list[dict]:
    recs = _records(repo_root)
    by_id = {r["id"]: r for r in recs}
    self = by_id.get(id)
    out, seen = [], set()
    if self:
        for rid in self.get("related", []):
            if rid in by_id and rid not in seen:
                out.append(by_id[rid]); seen.add(rid)
    for r in recs:
        if id in r.get("related", []) and r["id"] not in seen:
            out.append(r); seen.add(r["id"])
    return out


def stat(repo_root: Path) -> dict:
    recs = _records(repo_root)
    due = due_review(repo_root, dt.date.today())
    return {
        "total": len(recs),
        "by_type": dict(Counter(r["type"] for r in recs)),
        "by_domain": dict(Counter(d for r in recs for d in r["domain"])),
        "by_status": dict(Counter(r["status"] for r in recs)),
        "by_confidence": dict(Counter(r["confidence"] for r in recs)),
        "draft_backlog": sum(1 for r in recs if r["status"] == "draft"),
        "due_review": len(due),
    }


def due_review(repo_root: Path, today: dt.date) -> list[dict]:
    """时效到期待复核清单。

    第二十轮走查(§38): 修复前只认显式 `review_by`, 而该字段在生产链上从未被写入
    (消费链完好、生产链归零)——即便 accepted 落 review_by 后, **存量** accepted 条目
    仍无此字段, 会永久免检。故 accepted 无 review_by 时以 `updated + 复核周期`兜底,
    让历史条目自然纳入复核周期。draft/proposed 不兜底(尚未终审, 谈不上"复核到期")。
    """
    from kb.gate import REVIEW_CYCLE_DAYS
    out = []
    for p in sorted((Path(repo_root) / "kb").rglob("*.md")):
        e = parse_entry(p)
        rb = e.fm.get("review_by")
        if not rb and e.fm.get("status") == "accepted":
            upd = str(e.fm.get("updated", ""))[:10]
            try:
                rb = (dt.date.fromisoformat(upd)
                      + dt.timedelta(days=REVIEW_CYCLE_DAYS)).isoformat()
            except ValueError:
                continue  # updated 不可解析: 不猜到期日
        if rb and str(rb) <= today.isoformat():
            out.append({"id": e.fm.get("id"), "title": e.fm.get("title"),
                        "review_by": str(rb)})
    return out


def needs_scope(repo_root: Path) -> list[dict]:
    out = []
    kb = Path(repo_root) / "kb"
    for p in sorted(kb.rglob("*.md")) if kb.exists() else []:
        e = parse_entry(p)
        if "needs-scope-review" in (e.fm.get("tags") or []):
            out.append({"id": e.fm.get("id"), "title": e.fm.get("title"),
                        "type": e.fm.get("type"),
                        "domain": e.fm.get("domain", []),
                        "summary": e.summary()})
    return out
