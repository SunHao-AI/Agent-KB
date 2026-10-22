from pathlib import Path
import pytest
from kb.promote import promote
from kb.gate import set_scope
from kb.entry import parse_entry
from conftest import make_entry


def _put(repo, rel, text):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def test_promote_is_suggestion_only_no_scope_change(tmp_repo):
    """§39: AGENTS.md 红线2/README §4/spec §9/测试设定 C12 四处一致——promote 是纯
    建议(标记 needs-scope-review + promote-to), **不得改 scope**。旧实现复用
    set_scope 立即改 scope+清待办标签, 等于建议即终审, 人工确认环节被架空;
    还造成 scope 与物理位置错位(标 stack 躺项目仓)。落地仍由 set_scope/export 完成。
    """
    p = _put(tmp_repo, "kb/pitfall/frontend/a.md",
             make_entry(id="kb-20261012-aaaa", scope="project", status="accepted"))
    fm = promote(tmp_repo, "kb-20261012-aaaa", "stack")
    assert fm["scope"] == "project"  # 建议不改 scope
    assert "promoted" in fm["tags"] and "needs-scope-review" in fm["tags"]
    assert "promote-to:stack" in fm["tags"]  # 建议目标留痕
    assert parse_entry(p).fm["scope"] == "project"


def test_promote_stays_in_needs_scope_queue(tmp_repo):
    """建议发出后条目必须留在(或进入)人工终审待办清单——旧实现清 needs-scope-review
    会把刚发出的建议从 --needs-scope 里抹掉。"""
    from kb.query import needs_scope
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(id="kb-20261012-aaaa", scope="project", status="accepted",
                    tags=["vite"]))
    promote(tmp_repo, "kb-20261012-aaaa", "stack")
    assert [r["id"] for r in needs_scope(tmp_repo)] == ["kb-20261012-aaaa"]
    assert "vite" in parse_entry(tmp_repo / "kb" / "pitfall" / "frontend" / "a.md").fm["tags"]


def test_promote_twice_replaces_target_not_piles(tmp_repo):
    """重复 promote 视为改判目标: promote-to:* 替换不堆积。"""
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(id="kb-20261012-aaaa", scope="project", status="accepted"))
    fm = promote(tmp_repo, "kb-20261012-aaaa", "stack")
    fm = promote(tmp_repo, "kb-20261012-aaaa", "universal")
    assert "promote-to:universal" in fm["tags"]
    assert "promote-to:stack" not in fm["tags"]
    assert fm["tags"].count("promoted") == 1


def test_promote_does_not_change_status(tmp_repo):
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(id="kb-20261012-aaaa", scope="project", status="draft"))
    fm = promote(tmp_repo, "kb-20261012-aaaa", "universal")
    assert fm["status"] == "draft"


def test_set_scope_landing_clears_all_promote_tags(tmp_repo):
    """终审落地(set_scope)清掉**全部**建议期标签: needs-scope-review/promoted/
    promote-to:*——旧实现只清 needs-scope-review, promote-to:stack 会永久残留。"""
    _put(tmp_repo, "kb/pitfall/frontend/a.md",
         make_entry(id="kb-20261012-aaaa", scope="project", status="accepted",
                    tags=["needs-scope-review", "vite"]))
    promote(tmp_repo, "kb-20261012-aaaa", "stack")
    e = set_scope(tmp_repo, "kb-20261012-aaaa", "project")  # 人决定不上提
    assert e.fm["tags"] == ["vite"]
    assert e.fm["scope"] == "project"


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
