from __future__ import annotations
import json
from pathlib import Path


def _load(repo_root: Path):
    jl = Path(repo_root) / "kb" / "index.jsonl"
    if not jl.exists():
        return []
    return [json.loads(x) for x in jl.read_text(encoding="utf-8").splitlines() if x.strip()]


def _parts(rec: dict) -> list[tuple[str, str]]:
    # 拼接顺序与既有 hay 逐字节一致: title → tags → summary(空格分隔, 小写)
    return [("title", str(rec.get("title", "")).lower()),
            ("tags", " ".join(rec.get("tags", [])).lower()),
            ("summary", str(rec.get("summary", "")).lower())]


def _hit(parts, q: str) -> tuple[list[str], list[list[int]]]:
    """q 在拼接文本中的全部出现位置 + 反解命中的字段名(顺序按字段首现)。

    hay 与旧实现逐字节一致: 三段无条件空格拼接(空段同样产生分隔空格)。
    字段归属用区间相交判定(span 覆盖到分隔符即计入相邻字段)。
    """
    hay, bounds, pos = " ".join(text for _, text in parts), [], 0
    for name, text in parts:
        bounds.append((name, pos, pos + len(text)))
        pos += len(text) + 1
    fields: list[str] = []
    spans: list[list[int]] = []
    i = hay.find(q)
    while i >= 0:
        j = i + len(q)
        spans.append([i, j])
        for name, s, e in bounds:
            if i < e and j > s and name not in fields:
                fields.append(name)
        i = hay.find(q, i + 1)
    return fields, spans


def _filtered_out(rec, type, domain, tag, scope, status, confidence) -> bool:
    if type and rec["type"] != type:
        return True
    if domain and domain not in rec["domain"]:
        return True
    if tag and tag not in rec.get("tags", []):
        return True
    if scope and rec["scope"] != scope:
        return True
    if status and rec["status"] != status:
        return True
    if confidence and rec["confidence"] != confidence:
        return True
    return False


def evaluate(repo_root: Path, *, type=None, domain=None, tag=None, scope=None,
             status=None, confidence=None, query=None) -> tuple[list[dict], dict]:
    """全量评估(不截断): 返回 (命中行, 死因报告)。

    恒等式: rejected.filter + rejected.query + len(matched) == scanned。
    report 供 trace 埋点消费; rows 与改造前 search() 元素同形同序。
    """
    recs = _load(repo_root)
    q = query.lower() if query else None
    rows: list[dict] = []
    matched: list[dict] = []
    n_filter = n_query = 0
    for rec in recs:
        if _filtered_out(rec, type, domain, tag, scope, status, confidence):
            n_filter += 1
            continue
        fields, spans = ([], []) if q is None else _hit(_parts(rec), q)
        if q is not None and not fields:
            n_query += 1
            continue
        rows.append(rec)
        matched.append({"id": rec["id"], "title": rec.get("title"),
                        "scope": rec.get("scope"), "confidence": rec.get("confidence"),
                        "hit_fields": fields, "hit_spans": spans, "rank": len(matched) + 1})
    return rows, {"scanned": len(recs),
                  "rejected": {"filter": n_filter, "query": n_query},
                  "matched": matched}


def search(repo_root: Path, type=None, domain=None, tag=None, scope=None,
           status=None, confidence=None, query=None, limit: int = 20) -> list[dict]:
    rows, _ = evaluate(repo_root, type=type, domain=domain, tag=tag, scope=scope,
                       status=status, confidence=confidence, query=query)
    return rows[:limit]
