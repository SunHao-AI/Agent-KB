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


def _hit(parts, tokens: list[str]) -> tuple[list[str], list[list[int]]]:
    """AND 分词匹配: 每个 token 都须出现在拼接文本中(不要求连续)。

    任一 token 缺位 → 返回空(整条不命中)。spans 收集全部 token 的全部
    出现位置并按起点排序; hit_fields 按字段首现顺序。hay 拼接与旧实现一致
    (三段无条件空格拼接, 空段同样产生分隔空格)。
    """
    hay, bounds, pos = " ".join(text for _, text in parts), [], 0
    for name, text in parts:
        bounds.append((name, pos, pos + len(text)))
        pos += len(text) + 1
    spans: list[list[int]] = []
    for tok in tokens:
        tok_spans = []
        i = hay.find(tok)
        while i >= 0:
            tok_spans.append([i, i + len(tok)])
            i = hay.find(tok, i + 1)
        if not tok_spans:
            return [], []
        spans.extend(tok_spans)
    spans.sort()
    fields: list[str] = []
    for i, j in spans:
        for name, s, e in bounds:
            if i < e and j > s and name not in fields:
                fields.append(name)
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
    return bool(confidence and rec["confidence"] != confidence)


def evaluate(repo_root: Path, *, type=None, domain=None, tag=None, scope=None,
             status=None, confidence=None, query=None) -> tuple[list[dict], dict]:
    """全量评估(不截断): 返回 (命中行, 死因报告)。

    恒等式: rejected.filter + rejected.query + len(matched) == scanned。
    report 供 trace 埋点消费; rows 与改造前 search() 元素同形同序。
    """
    recs = _load(repo_root)
    tokens = query.lower().split() if query else []
    rows: list[dict] = []
    matched: list[dict] = []
    n_filter = n_query = 0
    for rec in recs:
        if _filtered_out(rec, type, domain, tag, scope, status, confidence):
            n_filter += 1
            continue
        fields, spans = ([], []) if not tokens else _hit(_parts(rec), tokens)
        if tokens and not fields:
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
