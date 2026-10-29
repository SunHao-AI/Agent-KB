from __future__ import annotations

import datetime as dt
import json
import math
import re
from pathlib import Path

# FR-3.1 多信号打分权重(PRD §FR-3.1, 数值以 trace 回放验收调参)。
_FIELD_WEIGHT = {"title": 5.0, "tags": 3.0, "keywords": 2.0, "sections": 1.5, "summary": 1.0}
_CONF_BONUS = {"verified": 0.2, "probable": 0.1}
_RECENCY_LAMBDA = 1 / 90.0  # exp(-Δupdated/90d)
_STALE_FACTOR = 0.3  # deprecated/superseded 降权
_CJK_RUN = re.compile(r"[\u4e00-\u9fff]{2,}")
_CJK_COVERAGE = 0.6  # FR-3.3: 2-gram 覆盖率达此值即判 token 命中


def _load(repo_root: Path):
    jl = Path(repo_root) / "kb" / "index.jsonl"
    if not jl.exists():
        return []
    return [json.loads(x) for x in jl.read_text(encoding="utf-8").splitlines() if x.strip()]


def _parts(rec: dict) -> list[tuple[str, str]]:
    # 前四段顺序与历史一致: title → tags → keywords → summary; sections 为 spec 4.2
    # 新增的"每段首句"面, 追加在末尾以最小化既有命中扰动(hay 仅在尾部多一个分隔空格,
    # 前四段的字段边界与整词/CJK 2-gram 判定均不受影响)。
    # keywords/sections 均为正文派生, 老索引无此字段自动为空。
    return [("title", str(rec.get("title", "")).lower()),
            ("tags", " ".join(rec.get("tags", [])).lower()),
            ("keywords", " ".join(str(k) for k in rec.get("keywords", [])).lower()),
            ("summary", str(rec.get("summary", "")).lower()),
            ("sections", str(rec.get("sections", "")).lower())]


def _token_spans(hay: str, tok: str) -> list[list[int]]:
    """单 token 在 hay 中的命中区间; 整词找不到时走 CJK 2-gram 覆盖率兜底。

    FR-3.3: 中文连写(如"推流死锁")整词 find 必零命中, 切 2-gram 后按覆盖率
    ≥0.6 判命中——跨词碎碰(只沾一个 gram)不放行, 属预期噪声防线。
    """
    spans = []
    i = hay.find(tok)
    while i >= 0:
        spans.append([i, i + len(tok)])
        i = hay.find(tok, i + 1)
    if spans:
        return spans
    segs = _CJK_RUN.findall(tok)
    if not segs:
        return []
    grams = [g for seg in segs for g in (seg[k:k + 2] for k in range(len(seg) - 1))]
    if not grams:
        return []
    covered, hit_spans = 0, []
    for g in dict.fromkeys(grams):  # 去重后计覆盖, 避免重复 gram 虚增分母
        found = False
        i = hay.find(g)
        while i >= 0:
            hit_spans.append([i, i + 2])
            found = True
            i = hay.find(g, i + 1)
        covered += found
    return hit_spans if covered / len(dict.fromkeys(grams)) >= _CJK_COVERAGE else []


def _hit(parts, tokens: list[str]) -> tuple[list[str], list[list[int]]]:
    """AND 分词匹配: 每个 token 都须命中拼接文本(不要求连续)。

    任一 token 缺位 → 返回空(整条不命中)。spans 收集全部 token 的全部
    出现位置并按起点排序; hit_fields 按字段首现顺序。hay 拼接与旧实现一致
    (各段无条件空格拼接, 空段同样产生分隔空格)。
    """
    hay, bounds, pos = " ".join(text for _, text in parts), [], 0
    for name, text in parts:
        bounds.append((name, pos, pos + len(text)))
        pos += len(text) + 1
    spans: list[list[int]] = []
    for tok in tokens:
        tok_spans = _token_spans(hay, tok)
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


def _score(rec: dict, fields: list[str], spans: list[list[int]],
           tokens: list[str], today: str) -> float:
    """FR-3.1: 字段权重(最高字段) × 命中密度 + 置信度加分 + 时效加分, 陈旧降权。"""
    if not fields:  # 无查询词时不过打分(排序保持稳定序)
        return 0.0
    base = max(_FIELD_WEIGHT.get(f, 1.0) for f in fields)
    n_tok = max(len(set(t.lower() for t in tokens)), 1)
    density = len(set((i, j) for i, j in spans)) / n_tok
    s = base * min(density, 3.0) / 3.0
    s += _CONF_BONUS.get(rec.get("confidence"), 0.0)
    upd = str(rec.get("updated", ""))[:10]
    if len(upd) == 10 and len(today) == 10:
        try:
            age = (dt.date.fromisoformat(today) - dt.date.fromisoformat(upd)).days
            s += 0.1 * math.exp(-max(age, 0) * _RECENCY_LAMBDA)
        except ValueError:
            pass
    if rec.get("status") in ("deprecated", "superseded"):
        s *= _STALE_FACTOR
    return round(s, 4)


def _suggest(titles: list[str], tokens: list[str], limit: int = 3) -> list[str]:
    """FR-3.2: 对标题分词做近似建议('你是想查 X?'), difflib 无新依赖。"""
    import difflib
    vocab: set[str] = set()
    for t in titles:
        vocab.update(w for w in re.split(r"\W+", t.lower()) if len(w) >= 2)
    out: list[str] = []
    for tok in tokens:
        for cand in difflib.get_close_matches(tok.lower(), sorted(vocab), n=1):
            if cand != tok.lower() and cand not in out:
                out.append(cand)
    return out[:limit]


def evaluate(repo_root: Path, *, type=None, domain=None, tag=None, scope=None,
             status=None, confidence=None, query=None) -> tuple[list[dict], dict]:
    """全量评估(不截断): 返回 (命中行[按分数降序], 死因报告)。

    恒等式: rejected.filter + rejected.query + len(matched) == scanned。
    report 供 trace 埋点消费; rows 与改造前 search() 元素同形, 但**有查询词时
    按 score 降序**(FR-3.1), 无查询词保持 index 序。零命中时 report 附
    `suggest` 近似词(FR-3.2), 供 MCP 透传与面板"已消化"判定。
    """
    recs = _load(repo_root)
    tokens = query.lower().split() if query else []
    today = dt.date.today().isoformat()  # 时效基准取当日(索引无构建时间字段)
    hits: list[tuple[float, int, dict, list[str], list[list[int]]]] = []
    n_filter = n_query = 0
    for order, rec in enumerate(recs):
        if _filtered_out(rec, type, domain, tag, scope, status, confidence):
            n_filter += 1
            continue
        fields, spans = ([], []) if not tokens else _hit(_parts(rec), tokens)
        if tokens and not fields:
            n_query += 1
            continue
        hits.append((_score(rec, fields, spans, tokens, today), order, rec, fields, spans))
    hits.sort(key=lambda h: (-h[0], h[1]))  # 分数降序, 同分保持 index 序(稳定可解释)
    matched = [{"id": h[2]["id"], "title": h[2].get("title"), "scope": h[2].get("scope"),
                "confidence": h[2].get("confidence"), "hit_fields": h[3],
                "hit_spans": h[4], "score": h[0], "rank": i + 1}
               for i, h in enumerate(hits)]
    rows = [h[2] for h in hits]
    report = {"scanned": len(recs),
              "rejected": {"filter": n_filter, "query": n_query},
              "matched": matched}
    if tokens and not hits:
        report["suggest"] = _suggest([r.get("title", "") for r in recs], tokens)
    return rows, report


def search(repo_root: Path, type=None, domain=None, tag=None, scope=None,
           status=None, confidence=None, query=None, limit: int = 20) -> list[dict]:
    rows, _ = evaluate(repo_root, type=type, domain=domain, tag=tag, scope=scope,
                       status=status, confidence=confidence, query=query)
    # limit 契约(§58 同族第五处, 第四十三轮): 公共库 API 的负数入参同样受
    # `[:-2]` 尾截翻转影响("要最少给最多"); ≤0 零名额, 与 sources/layers/
    # trace/feed 同契约——同族四处已修, 漏这一处即全族判据未落地完整。
    return rows[:limit] if limit > 0 else []
