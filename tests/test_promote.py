from pathlib import Path
from kb.promote import promote
from kb.entry import parse_entry
from conftest import make_entry


def _put(repo, rel, text):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_promote_sets_scope_and_tag(tmp_repo):
    p = _put(tmp_repo, "kb/pitfall/frontend/a.md",
             make_entry(id="kb-20261012-aaaa", scope="project", status="accepted"))
    fm = promote(tmp_repo, "kb-20261012-aaaa", "stack")
    assert fm["scope"] == "stack"
    assert "promoted" in fm["tags"]
    assert parse_entry(p).fm["scope"] == "stack"


def test_promote_does_not_change_status(tmp_repo):
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(id="kb-20261012-aaaa", scope="project", status="draft"))
    fm = promote(tmp_repo, "kb-20261012-aaaa", "universal")
    assert fm["status"] == "draft"
