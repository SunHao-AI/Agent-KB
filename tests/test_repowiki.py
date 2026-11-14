# tests/test_repowiki.py
import uuid
from pathlib import Path

import pytest
import yaml

from kb import repowiki
from kb.lint import lint_repo


def test_card_files_covers_five_cards():
    assert set(repowiki.CARD_FILES) == {
        "overview", "architecture_design", "tech_stack",
        "coding_conventions", "unique_setup_and_commands",
    }
    assert repowiki.CARD_FILES["architecture_design"] == "架构设计.md"
    assert repowiki.CARD_FILES["unique_setup_and_commands"] == "特殊配置与命令.md"


def test_managed_cards_subset_of_card_files():
    for c in repowiki.MANAGED_CARDS:
        assert c in repowiki.CARD_FILES


def test_default_type_card_maps_all_eight_types():
    assert set(repowiki.DEFAULT_TYPE_CARD) == {
        "decision", "spec", "plan", "retrospective", "rca", "pitfall",
        "howto", "reference",
    }
    for t in ("howto", "reference"):
        assert repowiki.DEFAULT_TYPE_CARD[t] == "unique_setup_and_commands"
    for t in ("decision", "spec", "plan", "retrospective", "rca", "pitfall"):
        assert repowiki.DEFAULT_TYPE_CARD[t] == "architecture_design"


def test_stable_uuid_deterministic_and_uuid5():
    a = repowiki.stable_uuid("docker_infra:architecture_design")
    b = repowiki.stable_uuid("docker_infra:architecture_design")
    c = repowiki.stable_uuid("docker_infra:unique_setup_and_commands")
    assert a == b and a != c
    assert str(uuid.UUID(a)) == a  # 合法 UUID


def _mk(kb_dir: Path, module) -> None:
    d = kb_dir / "kb" / "pitfall" / "backend"
    d.mkdir(parents=True, exist_ok=True)
    fm = {"id": "kb-20261114-a001", "title": "示例条目", "type": "pitfall",
          "domain": ["backend"], "scope": "project", "status": "accepted",
          "confidence": "verified", "created": "2026-11-14",
          "updated": "2026-11-14", "severity": "medium", "module": module}
    (d / "a.md").write_text("---\n" + yaml.safe_dump(fm, allow_unicode=True,
                            sort_keys=False) + f"---\n\n# 示例条目\n\n正文。\n",
                            encoding="utf-8")


def test_lint_accepts_module_string(tmp_path):
    _mk(tmp_path, "docker_infra")
    assert lint_repo(tmp_path) == []


def test_lint_accepts_module_null(tmp_path):
    _mk(tmp_path, None)
    assert lint_repo(tmp_path) == []


def test_lint_rejects_module_non_string(tmp_path):
    _mk(tmp_path, 42)
    errs = lint_repo(tmp_path)
    assert any("module" in e for e in errs)


def _tree(root: Path, *, schema_version: int = 1) -> Path:
    """最小 repowiki 导出: root 模块 + docker_infra 子模块。"""
    zh = root / ".qoder" / "repowiki" / "knowledge" / "zh"
    rdir = zh / "演示仓 demo"
    ddir = rdir / "Docker 基础设施与开发编排"
    ddir.mkdir(parents=True, exist_ok=True)
    modules = {
        "root": {"dir_name": "演示仓 demo", "title": "演示仓 demo",
                 "scope": ["README.md"], "source_files": [],
                 "children": ["docker_infra"], "depends_on": [], "related_to": []},
        "docker_infra": {"dir_name": "Docker 基础设施与开发编排",
                         "title": "Docker 基础设施与开发编排",
                         "scope": ["docker/"], "source_files": [],
                         "children": [], "depends_on": [], "related_to": []},
    }
    (zh / "_index.yaml").write_text(yaml.safe_dump(
        {"schema_version": schema_version, "locale": "zh-CN", "commit": "abc",
         "branch": "master", "exported_at": "2026-11-14T00:00:00Z",
         "modules": modules}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return zh


def _entry(kb_dir: Path, *, eid: str, type: str = "pitfall",
           module=None, status: str = "accepted") -> None:
    d = kb_dir / "kb" / type / "backend"
    d.mkdir(parents=True, exist_ok=True)
    fm = {"id": eid, "title": f"条目{eid}", "type": type, "domain": ["backend"],
          "scope": "project", "status": status, "confidence": "verified",
          "created": "2026-11-14", "updated": "2026-11-14"}
    if module is not None:
        fm["module"] = module
    (d / f"{eid}.md").write_text(
        "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False)
        + f"---\n\n# 条目{eid}\n\n正文内容一句。\n", encoding="utf-8")


def test_find_repowiki_root_sibling_layout(tmp_path):
    zh = _tree(tmp_path)
    assert repowiki.find_repowiki_root(tmp_path / "docs") == tmp_path / ".qoder" / "repowiki"
    # brief 原断言 `.parent == tmp_path` 与上一条对"不存在载体"要求返回
    # tmp_path/.qoder/repowiki 矛盾(两个不存在的同级目录无法由同一纯函数
    # 给出不同结果); 按 docstring 同级布局语义修正为等值断言。
    assert repowiki.find_repowiki_root(tmp_path / "missing") == \
        tmp_path / ".qoder" / "repowiki"


def test_find_repowiki_root_explicit_and_missing(tmp_path):
    zh = _tree(tmp_path)
    root = tmp_path / ".qoder" / "repowiki"
    assert repowiki.find_repowiki_root(tmp_path, explicit=str(root)) == root
    assert repowiki.find_repowiki_root(tmp_path, explicit=str(tmp_path / "nope")) is None
    # brief 原写法在 tmp_path 下建 bare: bare 的父级 tmp_path 有 .qoder/repowiki,
    # 按同级布局语义必命中, 不可能为 None; 移入无 repowiki 的其他项目根下,
    # 保留"探测两级均无果 → None"的本意。
    other = tmp_path / "otherproj"
    (other / "bare").mkdir(parents=True)
    assert repowiki.find_repowiki_root(other / "bare") is None


def test_load_module_tree_roundtrip(tmp_path):
    zh = _tree(tmp_path)
    modules, locale_dir = repowiki.load_module_tree(
        tmp_path / ".qoder" / "repowiki", "zh")
    assert modules["docker_infra"]["dir_name"] == "Docker 基础设施与开发编排"
    assert locale_dir == zh


def test_load_module_tree_missing_returns_none(tmp_path):
    assert repowiki.load_module_tree(tmp_path, "zh") is None


def test_load_module_tree_schema_guard(tmp_path):
    _tree(tmp_path, schema_version=2)
    with pytest.raises(ValueError, match="schema_version"):
        repowiki.load_module_tree(tmp_path / ".qoder" / "repowiki", "zh")


def test_module_dir_walks_dir_names(tmp_path):
    zh = _tree(tmp_path)
    modules, locale_dir = repowiki.load_module_tree(
        tmp_path / ".qoder" / "repowiki", "zh")
    assert repowiki.module_dir(locale_dir, modules, "root") == zh / "演示仓 demo"
    assert repowiki.module_dir(locale_dir, modules, "docker_infra") == \
        zh / "演示仓 demo" / "Docker 基础设施与开发编排"
    with pytest.raises(ValueError):
        repowiki.module_dir(locale_dir, modules, "ghost/mod")


def test_group_entries_skips_draft_and_unassigned(tmp_path):
    docs = tmp_path / "docs"
    _entry(docs, eid="kb-20261114-b001", module="docker_infra")
    _entry(docs, eid="kb-20261114-b002", module="docker_infra", status="draft")
    _entry(docs, eid="kb-20261114-b003")
    by_module, unassigned = repowiki.group_entries(docs)
    assert [e.fm["id"] for e in by_module["docker_infra"]] == ["kb-20261114-b001"]
    assert unassigned == ["kb-20261114-b003"]
