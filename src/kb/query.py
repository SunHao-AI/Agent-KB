from __future__ import annotations
import json
import datetime as dt
from collections import Counter
from pathlib import Path
from kb.entry import iter_entry_paths, parse_entry


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
    """正反向关联条目(发现面)。draft 邻接行剔除(第三十九轮走查 §57):
    `_records` 读 live+draft 双池让反向环能引用 draft 行——kb_search 承诺
    "draft 条目永不返回", 但 related 是第二条发现通道, 未对齐则草稿经
    related 字段(正向)或他人引用(反向)泄漏标题+摘要给 agent, 红线1"草稿
    不出土"绕道失效。self 可为 draft(人工 kb related 问自己的草稿, 邻人
    照报); get 面不受影响(已知 id 的读取面, 非发现面)。"""
    recs = _records(repo_root)
    by_id = {r["id"]: r for r in recs}
    self = by_id.get(id)
    out, seen = [], set()
    if self:
        for rid in self.get("related", []):
            r = by_id.get(rid)
            if r and r.get("status") != "draft" and rid not in seen:
                out.append(r); seen.add(rid)
    for r in recs:
        if r.get("status") == "draft":
            continue
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
    for p in iter_entry_paths(repo_root):   # 发现规则唯一事实源(§42)
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
    for p in iter_entry_paths(repo_root):   # 发现规则唯一事实源(§42)
        e = parse_entry(p)
        if "needs-scope-review" in (e.fm.get("tags") or []):
            out.append({"id": e.fm.get("id"), "title": e.fm.get("title"),
                        "type": e.fm.get("type"),
                        "domain": e.fm.get("domain", []),
                        "summary": e.summary()})
    return out
