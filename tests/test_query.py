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


def test_stat_counts(tmp_repo):
    _seed(tmp_repo)
    s = stat(tmp_repo)
    assert s["total"] == 2
    assert s["by_type"]["pitfall"] == 2


def test_due_review(tmp_repo):
    _seed(tmp_repo)
    due = due_review(tmp_repo, dt.date(2026, 10, 12))
    assert {r["id"] for r in due} == {"kb-20261012-aaaa"}
