"""FR-3.1 多信号排序 / FR-3.2 零命中建议 的专项回归。

覆盖 PRD 验收点: "授权"类查询首位为标题命中条目; 零命中附近似词。
"""
import json

from kb.search import evaluate, search


def _mk(root, recs):
    d = root / "kb"
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    return root


def _rec(i, title, *, tags=(), summary="s", confidence="verified",
         status="accepted", updated="2026-10-12"):
    return {"id": f"kb-{i}", "title": title, "type": "pitfall", "domain": ["backend"],
            "tags": list(tags), "scope": "project", "status": status,
            "confidence": confidence, "summary": summary,
            "path": f"kb/pitfall/backend/{i}.md", "updated": updated, "repo": "web"}


def test_title_hit_outranks_summary_hit(tmp_repo):
    """字段权重: 标题命中(5) 应压过摘要命中(1), 与写入顺序无关。"""
    _mk(tmp_repo, [
        _rec(1, "连接池调优", summary="本次故障与授权台账有关"),  # summary 命中
        _rec(2, "授权台账设计", summary="s"),                     # title 命中
    ])
    rows, rep = evaluate(tmp_repo, query="授权")
    assert [m["id"] for m in rep["matched"]] == ["kb-2", "kb-1"]
    assert rep["matched"][0]["score"] > rep["matched"][1]["score"]
    assert rep["matched"][0]["rank"] == 1 and rep["matched"][0]["hit_fields"] == ["title"]


def test_tags_hit_between_title_and_summary(tmp_repo):
    _mk(tmp_repo, [
        _rec(1, "甲", tags=["vite"], summary="s"),   # tags 3
        _rec(2, "乙 vite", summary="s"),             # title 5
        _rec(3, "丙", tags=[], summary="vite 相关"),  # summary 1
    ])
    _, rep = evaluate(tmp_repo, query="vite")
    assert [m["id"] for m in rep["matched"]] == ["kb-2", "kb-1", "kb-3"]


def test_higher_confidence_wins_on_ties(tmp_repo):
    _mk(tmp_repo, [
        _rec(1, "vite 抖动", confidence="probable"),
        _rec(2, "vite 卡顿", confidence="verified"),
    ])
    _, rep = evaluate(tmp_repo, query="vite")
    assert [m["id"] for m in rep["matched"]] == ["kb-2", "kb-1"]


def test_stale_status_downweighted(tmp_repo):
    _mk(tmp_repo, [
        _rec(1, "vite 老坑", status="deprecated"),
        _rec(2, "vite 新坑", status="accepted"),
    ])
    _, rep = evaluate(tmp_repo, query="vite")
    assert [m["id"] for m in rep["matched"]] == ["kb-2", "kb-1"]


def test_recency_breaks_otherwise_ties(tmp_repo):
    _mk(tmp_repo, [
        _rec(1, "vite 旧", updated="2025-01-01"),
        _rec(2, "vite 新", updated="2026-10-18"),
    ])
    _, rep = evaluate(tmp_repo, query="vite")
    assert [m["id"] for m in rep["matched"]] == ["kb-2", "kb-1"]


def test_no_query_keeps_index_order(tmp_repo):
    _mk(tmp_repo, [_rec(1, "b"), _rec(2, "a"), _rec(3, "c")])
    assert [r["id"] for r in search(tmp_repo, limit=10)] == ["kb-1", "kb-2", "kb-3"]


def test_identity_holds_with_ranking(tmp_repo):
    recs = [_rec(i, f"坑 {i}", tags=["vite"] if i % 2 else []) for i in range(10)]
    _mk(tmp_repo, recs)
    rows, rep = evaluate(tmp_repo, query="vite")
    assert rep["rejected"]["filter"] + rep["rejected"]["query"] + len(rep["matched"]) \
        == rep["scanned"]
    assert len(rows) == len(rep["matched"])


def test_zero_hit_suggests_near_words(tmp_repo):
    """FR-3.2: 零命中不再空手而归, 给出近似词供改写。"""
    _mk(tmp_repo, [_rec(1, "Vite HMR 不生效"), _rec(2, "Nginx 413 报错")])
    rows, rep = evaluate(tmp_repo, query="vitee")
    assert rows == [] and rep["matched"] == []
    assert "vite" in rep["suggest"]


def test_suggest_absent_when_hit(tmp_repo):
    _mk(tmp_repo, [_rec(1, "Vite HMR 不生效")])
    _, rep = evaluate(tmp_repo, query="vite")
    assert "suggest" not in rep
