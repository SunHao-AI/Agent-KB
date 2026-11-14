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


def _tree(root: Path, *, schema_version: int = 1, lang: str = "zh") -> Path:
    """最小 repowiki 导出: root 模块 + docker_infra 子模块。"""
    zh = root / ".qoder" / "repowiki" / "knowledge" / lang
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


import json
from kb.cli import _dispatch


def test_cli_repowiki_export_dry_run(tmp_path, capsys):
    _full_tree(tmp_path)
    docs = _docs_with_entries(tmp_path)
    rc = _dispatch(["repowiki", "export", "--repo", str(docs)])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "overlay" and "planned" in out


def test_cli_repowiki_export_write_and_conflict_exit(tmp_path, capsys):
    root, zh, rdir, ddir = _full_tree(tmp_path)
    docs = _docs_with_entries(tmp_path)
    assert _dispatch(["repowiki", "export", "--repo", str(docs),
                      "--write"]) == 0
    assert (ddir / "架构设计.md").exists()
    # 外部内容进入 managed 卡后再导出 → 拒绝, exit 1
    ddir.joinpath("架构设计.md").write_text("外部写入。\n", encoding="utf-8")
    assert _dispatch(["repowiki", "export", "--repo", str(docs),
                      "--write"]) == 1
    capsys.readouterr()


import os
from kb.repowiki import build_sidecar


def test_build_sidecar_indexes_all_card_files(tmp_path, capsys):
    root, zh, rdir, ddir = _full_tree(tmp_path)
    docs = _docs_with_entries(tmp_path)
    export_repowiki(docs, write=True)
    side = build_sidecar(docs)
    assert side == docs / "kb" / "index.repowiki.jsonl"
    recs = [json.loads(x) for x in side.read_text(encoding="utf-8").splitlines()
            if x.strip()]
    by_id = {r["id"]: r for r in recs}
    assert "repowiki://zh/docker_infra/architecture_design" in by_id
    native = by_id["repowiki://zh/root/overview"]
    assert native["summary"] == "原生概述内容。"
    assert native["kind"] == "repowiki_card"
    # path 相对载体(docs), 同级布局上探
    assert native["path"].startswith(".." + os.sep) or \
        native["path"].startswith("../")
    # L3 可用路径还原原文
    assert (docs / native["path"]).read_text(encoding="utf-8") == "原生概述内容。\n"


def test_build_sidecar_missing_tree_returns_none(tmp_path):
    docs = tmp_path / "docs"
    (docs / "kb").mkdir(parents=True)
    assert build_sidecar(docs) is None


def test_build_sidecar_schema_drift_skips_lang(tmp_path, capsys):
    _tree(tmp_path, schema_version=2)
    docs = tmp_path / "docs"
    (docs / "kb").mkdir(parents=True)
    assert build_sidecar(docs) is None
    assert "schema_version" in capsys.readouterr().err


def test_cli_index_builds_sidecar(tmp_path, capsys):
    _full_tree(tmp_path)
    docs = _docs_with_entries(tmp_path)
    export_repowiki(docs, write=True)
    from kb.index import build_indexes
    build_indexes(docs, repo_name="demo")
    rc = _dispatch(["index", "--repo", str(docs), "--repo-name", "demo"])
    assert rc == 0
    assert "index.repowiki.jsonl" in capsys.readouterr().out
    assert (docs / "kb" / "index.repowiki.jsonl").exists()


def _sidecar_ids(docs: Path) -> set:
    side = build_sidecar(docs)
    assert side is not None, "侧车应写出(存在未损坏模块)"
    return {json.loads(x)["id"]
            for x in side.read_text(encoding="utf-8").splitlines() if x.strip()}


def test_build_sidecar_bad_module_yaml_syntax_skips_module(tmp_path, capsys):
    zh = _tree(tmp_path)
    en = _tree(tmp_path, lang="en")
    (zh / "演示仓 demo" / "概述.md").write_text("原生概述内容。\n", encoding="utf-8")
    (en / "演示仓 demo" / "概述.md").write_text("native overview.\n",
                                               encoding="utf-8")
    # docker_infra 的 _module.yaml YAML 语法坏(yaml.YAMLError, 非 ValueError)
    (zh / "演示仓 demo" / "Docker 基础设施与开发编排" / "_module.yaml"
     ).write_text("kk_cards: [unclosed", encoding="utf-8")
    docs = tmp_path / "docs"
    (docs / "kb").mkdir(parents=True)
    ids = _sidecar_ids(docs)
    # 其他语言与同语言其他模块照常索引, 损坏模块不炸 kb index
    assert "repowiki://en/root/overview" in ids
    assert "repowiki://zh/root/overview" in ids
    assert not any(i.startswith("repowiki://zh/docker_infra/") for i in ids)
    assert "warning" in capsys.readouterr().err


def test_build_sidecar_non_mapping_module_yaml_skips_module(tmp_path, capsys):
    zh = _tree(tmp_path)
    (zh / "演示仓 demo" / "概述.md").write_text("原生概述内容。\n", encoding="utf-8")
    # _module.yaml 顶层是 list: data.get 抛 AttributeError
    (zh / "演示仓 demo" / "Docker 基础设施与开发编排" / "_module.yaml"
     ).write_text("- just\n- a\n- list\n", encoding="utf-8")
    docs = tmp_path / "docs"
    (docs / "kb").mkdir(parents=True)
    ids = _sidecar_ids(docs)
    assert "repowiki://zh/root/overview" in ids
    assert not any(i.startswith("repowiki://zh/docker_infra/") for i in ids)
    assert "warning" in capsys.readouterr().err


def test_build_sidecar_non_dict_module_meta_skips_module(tmp_path, capsys):
    zh = _tree(tmp_path)
    (zh / "演示仓 demo" / "概述.md").write_text("原生概述内容。\n", encoding="utf-8")
    # _index.yaml 里 docker_infra 的 meta 非 mapping
    idx = yaml.safe_load((zh / "_index.yaml").read_text(encoding="utf-8"))
    idx["modules"]["docker_infra"] = "not-a-mapping"
    (zh / "_index.yaml").write_text(yaml.safe_dump(idx, allow_unicode=True,
                                                  sort_keys=False),
                                    encoding="utf-8")
    docs = tmp_path / "docs"
    (docs / "kb").mkdir(parents=True)
    ids = _sidecar_ids(docs)
    assert "repowiki://zh/root/overview" in ids
    assert not any(i.startswith("repowiki://zh/docker_infra/") for i in ids)
    assert "warning" in capsys.readouterr().err


from kb.layers import search_layers_report
from kb.repowiki import make_repowiki_layer, search_sidecar
from kb.index import build_indexes


def _layer_setup(tmp_path):
    """项目层命中 + repowiki 层命中 + agent-kb 层命中, 验证优先级与截断。"""
    root, zh, rdir, ddir = _full_tree(tmp_path)
    docs = tmp_path / "docs"
    (docs / "kb").mkdir(parents=True)
    d = docs / "kb" / "howto" / "backend"
    d.mkdir(parents=True)
    (d / "x.md").write_text(
        "---\n" + yaml.safe_dump(
            {"id": "kb-20261114-d001", "title": "Redis 连接超时排查",
             "type": "howto", "domain": ["backend"], "scope": "project",
             "status": "accepted", "confidence": "verified",
             "created": "2026-11-14", "updated": "2026-11-14",
             # brief 原夹具无 module 归属(卡片全为占位), 其 priority 测试却要求
             # query="Redis" 在 repowiki 层有 kind 行——两者矛盾。按测试意图补
             # module 归属: 条目投影进 docker_infra 的特殊配置与命令卡, repowiki
             # 层对 "Redis" 才有命中; 全部断言与实现仍逐字沿用 brief。
             "module": "docker_infra"},
            allow_unicode=True, sort_keys=False)
        + "---\n\n# Redis 连接超时排查\n\n正文。\n", encoding="utf-8")
    build_indexes(docs, repo_name="demo")
    export_repowiki(docs, write=True)  # 条目归属 docker_infra → howto 卡含标题
    build_sidecar(docs)
    agent = tmp_path / "agentkb"
    (agent / "kb").mkdir(parents=True)
    return docs, agent


def test_search_sidecar_matches_query(tmp_path):
    docs, _agent = _layer_setup(tmp_path)
    rows, rep = search_sidecar(docs, query="原生概述")
    assert [r["id"] for r in rows] == ["repowiki://zh/root/overview"]
    assert rows[0]["kind"] == "repowiki_card"
    assert rep["rejected"]["filter"] + rep["rejected"]["query"] \
        + len(rep["matched"]) == rep["scanned"]
    assert search_sidecar(docs, query="不存在的词xyz")[0] == []


def test_search_layers_three_layer_priority(tmp_path):
    docs, agent = _layer_setup(tmp_path)
    between = make_repowiki_layer(docs)
    rows, reports = search_layers_report(
        [docs, agent], query="Redis", limit=10, between=between)
    assert rows[0]["id"] == "kb-20261114-d001"  # 项目层优先
    assert reports[1]["repo"] == "repowiki"
    # repowiki 层行带 kind, 且排在 agent-kb 之前
    kinds = [r.get("kind") for r in rows]
    assert kinds[0] is None and any(k == "repowiki_card" for k in kinds)


def test_search_layers_without_between_unchanged(tmp_path):
    docs, agent = _layer_setup(tmp_path)
    rows, reports = search_layers_report([docs, agent], query="Redis", limit=10)
    assert [r["id"] for r in rows] == ["kb-20261114-d001"]
    assert len(reports) == 2


def test_cli_search_includes_repowiki_layer(tmp_path, capsys):
    docs, agent = _layer_setup(tmp_path)
    (agent / "kb" / "index.jsonl").write_text("", encoding="utf-8")
    rc = _dispatch(["search", "--repo", str(docs),
                    "--agent-kb", str(agent), "--query", "原生概述"])
    assert rc == 0
    rows = json.loads(capsys.readouterr().out)
    assert rows[0]["kind"] == "repowiki_card"
    assert rows[0]["id"] == "repowiki://zh/root/overview"


def test_cli_search_corrupt_sidecar_degrades_to_two_layers(tmp_path, capsys):
    docs, agent = _layer_setup(tmp_path)
    side = docs / "kb" / "index.repowiki.jsonl"
    lines = side.read_text(encoding="utf-8").splitlines()
    lines[0] = "{ not valid json"
    side.write_text("\n".join(lines) + "\n", encoding="utf-8")
    (agent / "kb" / "index.jsonl").write_text("", encoding="utf-8")
    rc = _dispatch(["search", "--repo", str(docs),
                    "--agent-kb", str(agent), "--query", "原生概述"])
    assert rc == 0  # 损坏侧车不击穿 kb search
    captured = capsys.readouterr()
    rows = json.loads(captured.out)
    assert all(r.get("kind") != "repowiki_card" for r in rows)
    assert "warning" in captured.err


def test_search_sidecar_missing_key_record_degrades(tmp_path, capsys):
    docs = tmp_path / "docs"
    (docs / "kb").mkdir(parents=True)
    (docs / "kb" / "index.repowiki.jsonl").write_text(
        json.dumps({"kind": "repowiki_card", "id": "repowiki://zh/a/overview",
                    "module_path": "a", "card": "overview",
                    # 缺 title/summary 键
                    }) + "\n", encoding="utf-8")
    rows, rep = search_sidecar(docs, query="原生概述")
    assert rows == []
    assert rep == {"scanned": 0, "rejected": {"filter": 0, "query": 0},
                   "matched": []}
    assert "warning" in capsys.readouterr().err
