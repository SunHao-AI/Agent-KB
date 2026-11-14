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


def test_module_yaml_update_rejects_non_mapping_existing(tmp_path):
    with pytest.raises(ValueError, match="非 mapping"):
        repowiki._module_yaml_update(tmp_path / "m", "root", "根", ["not", "a", "dict"])


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


def test_load_module_tree_bad_yaml_raises_value_error(tmp_path):
    zh = _tree(tmp_path)
    # 未闭合流式序列触发 yaml.YAMLError, 须转成 ValueError
    (zh / "_index.yaml").write_text("schema_version: 1\nmodules: [root, docker",
                                    encoding="utf-8")
    with pytest.raises(ValueError, match="YAML 解析失败"):
        repowiki.load_module_tree(tmp_path / ".qoder" / "repowiki", "zh")


from kb.repowiki import export_repowiki


def _mod_yaml(path: Path, module_path: str, title: str, kk_module_id: str) -> None:
    (path / "_module.yaml").write_text(yaml.safe_dump(
        {"schema_version": 1, "module_path": module_path, "title": title,
         "scope": [], "source_files": [], "depends_on": [], "related_to": [],
         "kk_module_id": kk_module_id,
         "kk_cards": {c: {"id": f"11111111-2222-3333-4444-{i:012d}",
                          "title": title}
                      for i, c in enumerate(repowiki.CARD_FILES)},
         "kk_repo_cards": []}, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _full_tree(tmp_path):
    """带 _module.yaml 与原生概述卡的完整 overlay 夹具。"""
    zh = _tree(tmp_path)
    repowiki.find_repowiki_root(tmp_path)  # 探测无异常即可
    root = tmp_path / ".qoder" / "repowiki"
    modules, _ = repowiki.load_module_tree(root, "zh")
    rdir = zh / "演示仓 demo"
    ddir = rdir / "Docker 基础设施与开发编排"
    _mod_yaml(rdir, "root", "演示仓 demo", "00000000-0000-0000-0000-0000000000aa")
    _mod_yaml(ddir, "docker_infra", "Docker 基础设施与开发编排",
              "00000000-0000-0000-0000-0000000000bb")
    (rdir / "概述.md").write_text("原生概述内容。\n", encoding="utf-8")
    return root, zh, rdir, ddir


def _docs_with_entries(tmp_path):
    docs = tmp_path / "docs"
    _entry(docs, eid="kb-20261114-c001", type="pitfall", module="docker_infra")
    _entry(docs, eid="kb-20261114-c002", type="howto", module="docker_infra")
    _entry(docs, eid="kb-20261114-c003", type="pitfall")  # 未归属
    return docs


def test_export_dry_run_default_writes_nothing(tmp_path):
    root, zh, rdir, ddir = _full_tree(tmp_path)
    docs = _docs_with_entries(tmp_path)
    report = export_repowiki(docs)
    assert report["mode"] == "overlay"
    assert not (ddir / "架构设计.md").exists()
    assert report["planned"], "dry-run 也应列出将写文件"
    assert set(report["unassigned"]) == {"kb-20261114-c003"}
    assert report["warnings"] == []


def test_export_write_renders_managed_cards(tmp_path):
    root, zh, rdir, ddir = _full_tree(tmp_path)
    docs = _docs_with_entries(tmp_path)
    report = export_repowiki(docs, write=True)
    card = (ddir / "架构设计.md").read_text(encoding="utf-8")
    assert card.startswith(repowiki.TOOL_MARKER)
    assert "已知陷阱 (pitfall)" in card
    assert "**条目kb-20261114-c001**" in card and "kb-20261114-c001" in card
    how = (ddir / "特殊配置与命令.md").read_text(encoding="utf-8")
    assert "操作指引 (howto)" in how and "kb-20261114-c002" in how
    # type→卡路由互斥: 架构设计卡不含 howto 节, 特殊配置与命令卡不含 pitfall 节
    assert "操作指引" not in card
    assert "已知陷阱" not in how
    # 原生卡不被触碰
    assert (rdir / "概述.md").read_text(encoding="utf-8") == "原生概述内容。\n"


def test_export_module_yaml_overlay_preserves_native_ids(tmp_path):
    root, zh, rdir, ddir = _full_tree(tmp_path)
    docs = _docs_with_entries(tmp_path)
    export_repowiki(docs, write=True)
    data = yaml.safe_load((ddir / "_module.yaml").read_text(encoding="utf-8"))
    assert data["kk_module_id"] == "00000000-0000-0000-0000-0000000000bb"
    # 非 managed 卡保留原生 UUID; managed 卡换成本工具确定性 UUID
    assert data["kk_cards"]["overview"]["id"] == \
        "11111111-2222-3333-4444-000000000000"
    got = data["kk_cards"]["architecture_design"]["id"]
    assert got == repowiki.stable_uuid("docker_infra:architecture_design")
    assert data["kk_cards"]["tech_stack"]["id"] == \
        "11111111-2222-3333-4444-000000000002"


def test_export_index_yaml_updates_head_fields(tmp_path):
    root, zh, rdir, ddir = _full_tree(tmp_path)
    docs = _docs_with_entries(tmp_path)
    export_repowiki(docs, write=True)
    data = yaml.safe_load((zh / "_index.yaml").read_text(encoding="utf-8"))
    # tmp 布局无 .git: commit/branch 归空, exported_at 必更新
    assert data["commit"] == "" and data["branch"] == ""
    assert data["exported_at"] != "2026-11-14T00:00:00Z"
    assert "docker_infra" in data["modules"]


def test_export_deterministic(tmp_path):
    root, zh, rdir, ddir = _full_tree(tmp_path)
    docs = _docs_with_entries(tmp_path)
    export_repowiki(docs, write=True)
    first = {p.name: p.read_text(encoding="utf-8")
             for p in (ddir / "架构设计.md", ddir / "特殊配置与命令.md")}
    export_repowiki(docs, write=True)
    assert (ddir / "架构设计.md").read_text(encoding="utf-8") == first["架构设计.md"]
    assert (ddir / "特殊配置与命令.md").read_text(encoding="utf-8") == \
        first["特殊配置与命令.md"]


def test_export_refuses_foreign_managed_card_without_force(tmp_path):
    root, zh, rdir, ddir = _full_tree(tmp_path)
    ddir.joinpath("架构设计.md").write_text("Qoder 原生生成的架构内容。\n",
                                            encoding="utf-8")
    docs = _docs_with_entries(tmp_path)
    with pytest.raises(ValueError, match="force"):
        export_repowiki(docs, write=True)
    # --force 放行
    report = export_repowiki(docs, write=True, force=True)
    assert (ddir / "架构设计.md").read_text(encoding="utf-8").startswith(
        repowiki.TOOL_MARKER)
    assert any("force" in w or "覆盖" in w for w in report["warnings"])


def test_export_skeleton_from_modules_yaml(tmp_path):
    docs = _docs_with_entries(tmp_path)
    myaml = tmp_path / "modules.yaml"
    myaml.write_text(yaml.safe_dump({"modules": {
        "root": {"dir_name": "演示仓 demo", "title": "演示仓 demo",
                 "scope": ["README.md"], "children": ["docker_infra"]},
        "docker_infra": {"dir_name": "Docker 基础设施与开发编排",
                         "title": "Docker 基础设施与开发编排",
                         "scope": ["docker/"], "children": []},
    }}, allow_unicode=True, sort_keys=False), encoding="utf-8")
    out = tmp_path / "out"
    report = export_repowiki(docs, out=out, modules=myaml, write=True)
    assert report["mode"] == "skeleton"
    ddir = out / "knowledge" / "zh" / "演示仓 demo" / "Docker 基础设施与开发编排"
    assert (ddir / "架构设计.md").exists()
    assert (ddir / "概述.md").exists() is False  # skeleton 不生成原生卡
    data = yaml.safe_load((out / "knowledge" / "zh" / "_index.yaml")
                          .read_text(encoding="utf-8"))
    assert data["schema_version"] == 1 and "docker_infra" in data["modules"]


def test_export_skeleton_requires_modules(tmp_path):
    docs = tmp_path / "docs"
    with pytest.raises(FileNotFoundError):
        export_repowiki(docs, write=True)


def test_export_schema_drift_is_fatal(tmp_path):
    _tree(tmp_path, schema_version=2)
    docs = tmp_path / "docs"
    with pytest.raises(ValueError, match="schema_version"):
        export_repowiki(docs, out=tmp_path / ".qoder" / "repowiki")
