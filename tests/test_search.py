from pathlib import Path
from kb.index import build_indexes
from kb.search import search
from conftest import make_entry


def _put(repo, rel, text):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _seed(tmp_repo):
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(id="kb-20261012-aaaa", title="Vite HMR", domain=["frontend"],
                    tags=["vite"], status="accepted", confidence="verified"))
    _put(tmp_repo, "kb/pitfall/backend/b.md",
         make_entry(id="kb-20261012-bbbb", title="SQL pool", domain=["backend"],
                    tags=["db"], status="accepted", confidence="verified"))
    build_indexes(tmp_repo)


def test_filter_by_domain(tmp_repo):
    _seed(tmp_repo)
    res = search(tmp_repo, domain="backend")
    assert [r["id"] for r in res] == ["kb-20261012-bbbb"]


def test_query_matches_summary_or_title(tmp_repo):
    _seed(tmp_repo)
    res = search(tmp_repo, query="vite")
    assert [r["id"] for r in res] == ["kb-20261012-aaaa"]


def test_never_returns_body(tmp_repo):
    _seed(tmp_repo)
    res = search(tmp_repo, limit=10)
    assert all("body" not in r for r in res)


def test_draft_excluded(tmp_repo):
    _put(tmp_repo, "kb/pitfall/frontend/d.md",
         make_entry(id="kb-20261012-dddd", status="draft"))
    build_indexes(tmp_repo)
    assert search(tmp_repo, query="demo") == []
