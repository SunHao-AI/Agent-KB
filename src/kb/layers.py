from __future__ import annotations

from pathlib import Path

from kb.query import get_entry, related
from kb.search import evaluate


def _name(repo: Path) -> str:
    # 与 index 写入的 repo 字段同口径(小写规范名), 保证 search 行与 get 层标签一致
    return Path(repo).resolve().name.lower()


def search_layers_report(repos: list[Path], *, type=None, domain=None, tag=None,
                         scope=None, status=None, confidence=None, query=None,
                         limit: int = 10, between=None) -> tuple[list[dict], list[dict]]:
    """双层合并检索 + 逐层死因报告(供 trace)。repos 顺序即优先级, 逐层取满即截断。

    between(可选): 插入第一层 kb 与剩余层之间的中间层(如 repowiki), 签名
    (take, *, type, domain, tag, query) -> (rows, report), rows 不限长由本函数
    截断; None 时行为与旧版逐字节一致。

    rows 元素附 `hit_fields`/`hit_spans`(来自同层 matched, 按 id 对齐):
    FR-4.1 要求把"为什么命中"透传给 agent, 比 summary 更省 token 更快回答。

    limit 契约(第三十八轮走查, 与 sources.search §51 同族): 非数值回退 10、
    上限 100 防误用、**limit<=0 截零短路**——旧实现 `max(0, limit-len(out))`
    让每层 take 恒为 0, 但 report 照扫全库, MCP 零命中分支据此产出"scanned N:
    死于过滤器 0, 死于词匹配 0"的自相矛盾 hint, 把 agent 引向"改短查询词"的
    错误自救(真相是 limit=0 根本不给名额)。非数值/越界要在这里归一, 是因为
    MCP JSONSchema 的 int 不拒负数、JSON 允许小数, 校验层拦不住。
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    limit = max(0, min(limit, 100))
    out: list[dict] = []
    reports: list[dict] = []
    seq: list[tuple[str, object]] = [("kb", rp) for rp in repos]
    if between is not None and seq:
        seq = seq[:1] + [("repowiki", None)] + seq[1:]
    for kind, rp in seq:
        if limit <= 0:  # 零名额: 不扫后端, 空 report 也要保持恒等式可用
            reports.append({"repo": "repowiki" if kind == "repowiki" else _name(rp),
                            "scanned": 0,
                            "rejected": {"filter": 0, "query": 0},
                            "matched": [], "taken": 0,
                            "truncated_at_limit": False})
            continue
        take = max(0, limit - len(out))
        if kind == "repowiki":
            rows, rep = between(take, type=type, domain=domain, tag=tag,
                                query=query)
            chosen = rows[:take]
            rep.update({"repo": "repowiki", "taken": len(chosen),
                        "truncated_at_limit": len(chosen) < len(rows)})
            reports.append(rep)
            out.extend(chosen)
            continue
        rows, rep = evaluate(rp, type=type, domain=domain, tag=tag, scope=scope,
                             status=status, confidence=confidence, query=query)
        chosen = rows[:take]
        by_id = {m["id"]: m for m in rep["matched"]}
        for r in chosen:
            m = by_id.get(r["id"])
            if m:
                r["hit_fields"] = m["hit_fields"]
                r["hit_spans"] = m["hit_spans"]
        rep.update({"repo": _name(rp), "taken": len(chosen),
                    "truncated_at_limit": len(chosen) < len(rows)})
        reports.append(rep)
        out.extend(chosen)
    return out[:limit], reports


def search_layers(repos: list[Path], *, type=None, domain=None, tag=None, scope=None,
                  status=None, confidence=None, query=None, limit: int = 10) -> list[dict]:
    """双层合并检索: repos 顺序即优先级, 逐层取满即截断(spec §7)。"""
    rows, _ = search_layers_report(repos, type=type, domain=domain, tag=tag, scope=scope,
                                   status=status, confidence=confidence, query=query,
                                   limit=limit)
    return rows


def get_layered(repos: list[Path], id: str) -> tuple[str, str] | None:
    for rp in repos:
        text = get_entry(rp, id)
        if text:
            return text, _name(rp)
    return None


def related_layers(repos: list[Path], id: str) -> list[dict]:
    out, seen = [], set()
    for rp in repos:
        for r in related(rp, id):
            if r["id"] not in seen:
                out.append(r)
                seen.add(r["id"])
    return out
