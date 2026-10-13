from pathlib import Path
import pytest
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


def test_promote_clears_needs_scope_review_tag(tmp_repo):
    # promote 必须复用 gate.set_scope 写路径: 清 needs-scope-review + 追加 promoted
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(id="kb-20261012-aaaa", scope="project", status="accepted",
                    tags=["needs-scope-review", "vite"]))
    fm = promote(tmp_repo, "kb-20261012-aaaa", "stack")
    assert fm["tags"] == ["vite", "promoted"]
    assert parse_entry(tmp_repo / "kb" / "pitfall" / "frontend" / "a.md").fm["tags"] \
        == ["vite", "promoted"]


def test_promote_rejects_scope_outside_taxonomy(tmp_repo):
    # 非法 --to 必须被枚举校验拒绝, 不得裸写落盘
    p = _put(tmp_repo, "kb/pitfall/frontend/a.md",
             make_entry(id="kb-20261012-aaaa", scope="project", status="accepted"))
    with pytest.raises(ValueError):
        promote(tmp_repo, "kb-20261012-aaaa", "global")
    assert parse_entry(p).fm["scope"] == "project"


def test_promote_rejects_project_target(tmp_repo):
    # promote 目标 scope 限 stack/universal: 项目库内退回 project 无意义
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(id="kb-20261012-aaaa", scope="project", status="accepted"))
    with pytest.raises(ValueError):
        promote(tmp_repo, "kb-20261012-aaaa", "project")
