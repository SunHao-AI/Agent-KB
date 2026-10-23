import datetime as dt
from pathlib import Path
from kb.index import build_indexes
from kb.query import get_entry, related, stat, due_review
from conftest import make_entry


def _put(repo, rel, text):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _seed(tmp_repo):
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(id="kb-20261012-aaaa", status="accepted",
                    related=["kb-20261012-bbbb"], review_by="2020-01-01"))
    _put(tmp_repo, "kb/pitfall/backend/b.md",
         make_entry(id="kb-20261012-bbbb", status="accepted"))
    build_indexes(tmp_repo)


def test_get_entry_returns_full_text(tmp_repo):
    _seed(tmp_repo)
    text = get_entry(tmp_repo, "kb-20261012-aaaa")
    assert text and "首段摘要" in text
    assert get_entry(tmp_repo, "kb-20261012-ffff") is None


def test_related_bidirectional(tmp_repo):
    _seed(tmp_repo)
    rel = related(tmp_repo, "kb-20261012-bbbb")
    assert {r["id"] for r in rel} == {"kb-20261012-aaaa"}


def test_related_excludes_draft_neighbors(tmp_repo):
    """§57(第三十九轮): related 是第二条发现通道, draft 邻接行必须剔除——
    正向(accepted 引用 draft)与反向(draft 引用 accepted, 环带出 draft 行)
    两条泄漏路径都堵; self 是 draft 时邻人照报(人工问自己的草稿)。"""
    _put(tmp_repo, "kb/pitfall/frontend/x.md",
         make_entry(id="kb-20261012-xxxx", status="accepted",
                    related=["kb-20261012-dddd"]))  # 正向指向 draft
    _put(tmp_repo, "kb/pitfall/frontend/d.md",
         make_entry(id="kb-20261012-dddd", status="draft",
                    related=["kb-20261012-xxxx"]))  # 反向引用 accepted
    build_indexes(tmp_repo)
    rel = related(tmp_repo, "kb-20261012-xxxx")
    assert rel == []  # 正向 draft 邻居被剔
    # self 为 draft: 自己的 accepted 邻人照报
    rel_d = related(tmp_repo, "kb-20261012-dddd")
    assert {r["id"] for r in rel_d} == {"kb-20261012-xxxx"}


def test_stat_counts(tmp_repo):
    _seed(tmp_repo)
    s = stat(tmp_repo)
    assert s["total"] == 2
    assert s["by_type"]["pitfall"] == 2


def test_due_review(tmp_repo):
    _seed(tmp_repo)
    due = due_review(tmp_repo, dt.date(2026, 10, 12))
    assert {r["id"] for r in due} == {"kb-20261012-aaaa"}


def test_needs_scope_lists_tagged(tmp_repo):
    from kb.query import needs_scope
    d = tmp_repo / "kb" / "pitfall" / "backend"
    d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261014-a1a1", tags=["needs-scope-review"]), encoding="utf-8")
    (d / "b.md").write_text(make_entry(id="kb-20261014-b2b2", tags=["vite"]), encoding="utf-8")
    rows = needs_scope(tmp_repo)
    assert [r["id"] for r in rows] == ["kb-20261014-a1a1"]
