# Agent-KB ↔ RepoWiki 双向桥 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 kb CLI/MCP 增加 RepoWiki 桥——`kb repowiki export` 把项目库条目按 `module` 归属聚合投影为 `.qoder/repowiki/knowledge/zh/` 格式（overlay，只写两类 managed 卡），并把 RepoWiki 卡纳入 `kb search` 三层命中与 `kb show`/`kb_get` 读原文。

**Architecture:** 新增 `src/kb/repowiki.py` 单一模块承载格式原语（卡枚举映射、确定性 UUID5、模块树加载、导出渲染、侧车索引、检索、L3 读卡）；`layers.py` 增加 `between` 注入点（project kb 与 agent-kb 之间插入 repowiki 层，默认 None 行为逐字节不变）；CLI/MCP 只做薄接线。事实源仍是 kb 条目，repowiki 是幂等可重建的投影。

**Tech Stack:** Python ≥3.10，pyyaml/jsonschema（无新依赖），pytest。

spec：`docs/superpowers/specs/2026-11-14-repowiki-bridge-design.md`

## Global Constraints

- 无新第三方依赖；只允许 `pyyaml`、`jsonschema`、标准库。
- 写文件一律经 `kb.fskit.write_text_lf`（LF 归一，仓内既有红线）。
- 源文件编码与字符串：UTF-8；CLI 输出 JSON 用 `ensure_ascii=False`。
- 测试运行器（仓根执行）：`.venv/Scripts/python.exe -m pytest tests/<file> -q`（Windows Git Bash；POSIX 用 `.venv/bin/python`）。
- 提交风格对齐仓内惯例：`feat(repowiki): …` / `test(repowiki): …`，**只 add 本任务列出的文件**，绝不 `git add -A`（工作区有他人未提交的 templates/、traces/ 改动）。
- draft 条目永不导出（红线 1 对齐）；导出卡内容只放条目投影（标题+summary+kb id），不搬全文。
- 不改 `kb/index.jsonl` 记录形状；repowiki 检索面走独立侧车 `kb/index.repowiki.jsonl`。
- `git status` 出现本计划外文件变更时停下核对，不替他人收尾。

---

### Task 1: repowiki 格式原语（新模块骨架）

**Files:**
- Create: `src/kb/repowiki.py`
- Test: `tests/test_repowiki.py`

**Interfaces:**
- Produces（后续任务全部依赖）:
  - `TOOL_MARKER: str`（值 `<!-- kb-repowiki-export -->`）——managed 卡指纹标记
  - `CARD_FILES: dict[str, str]`——5 个卡枚举 → 中文文件名
  - `MANAGED_CARDS: tuple[str, str]` = `("architecture_design", "unique_setup_and_commands")`
  - `DEFAULT_TYPE_CARD: dict[str, str]`——8 个 type → 卡枚举
  - `TYPE_SECTION_TITLES: dict[str, str]`——type → 中文分节名
  - `REPOWIKI_ID_PREFIX: str` = `"repowiki://"`；`SIDECAR_NAME: str` = `"index.repowiki.jsonl"`；`SCHEMA_VERSION: int` = 1
  - `stable_uuid(key: str) -> str`——确定性 UUID5

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repowiki.py
import uuid

from kb import repowiki


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py -q`
Expected: FAIL（`ModuleNotFoundError: No module named 'kb.repowiki'`）

- [ ] **Step 3: Write minimal implementation**

```python
# src/kb/repowiki.py
"""Agent-KB ↔ Qoder RepoWiki 双向桥(spec 2026-11-14)。

导出器把项目库条目按 `module` front-matter 归属聚合进 RepoWiki 的两类 managed 卡
(架构设计/特殊配置与命令), overlay 到 `.qoder/repowiki/knowledge/<lang>/`;
检索面经 `index.repowiki.jsonl` 侧车把 RepoWiki 卡纳入 kb search 三层命中。
"""
from __future__ import annotations

import uuid

TOOL_MARKER = "<!-- kb-repowiki-export -->"
SCHEMA_VERSION = 1
SIDECAR_NAME = "index.repowiki.jsonl"
REPOWIKI_ID_PREFIX = "repowiki://"

CARD_FILES = {
    "overview": "概述.md",
    "architecture_design": "架构设计.md",
    "tech_stack": "技术栈.md",
    "coding_conventions": "编码规范.md",
    "unique_setup_and_commands": "特殊配置与命令.md",
}
MANAGED_CARDS = ("architecture_design", "unique_setup_and_commands")
DEFAULT_TYPE_CARD = {
    "decision": "architecture_design",
    "spec": "architecture_design",
    "plan": "architecture_design",
    "retrospective": "architecture_design",
    "rca": "architecture_design",
    "pitfall": "architecture_design",
    "howto": "unique_setup_and_commands",
    "reference": "unique_setup_and_commands",
}
TYPE_SECTION_TITLES = {
    "pitfall": "已知陷阱", "rca": "根因分析", "decision": "决策记录",
    "spec": "规格说明", "plan": "计划", "retrospective": "回顾",
    "howto": "操作指引", "reference": "参考资料",
}


def stable_uuid(key: str) -> str:
    """确定性 UUID5(namespace=固定常量+key): 同输入幂等重建, 是本工具的文件指纹。"""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "kb-repowiki:" + key))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py -q`
Expected: PASS（4 passed）

- [ ] **Step 5: Commit**

```bash
git add src/kb/repowiki.py tests/test_repowiki.py
git commit -m "feat(repowiki): 格式原语(卡枚举映射/确定性 UUID5/工具标记)"
```

---

### Task 2: front-matter 新增可选 `module` 字段

**Files:**
- Modify: `src/kb/taxonomy.py`（`derive_schema` 的 `props` dict，约 47 行 `"supersedes"` 之后）
- Modify: `schema/frontmatter.schema.json`（与 derive_schema 同步的检入产物）
- Test: `tests/test_repowiki.py`（追加）

**Interfaces:**
- Produces: lint/schema 接受 `module: <str>` 或 `module: null`；拒绝非字符串标量（如 int）——导出器靠它做归属分组键。

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_repowiki.py`：

```python
import yaml
from kb.lint import lint_repo


def _mk(kb_dir: Path, module) -> None:
    d = kb_dir / "kb" / "pitfall" / "backend"
    d.mkdir(parents=True, exist_ok=True)
    fm = {"id": "kb-20261114-a001", "title": "示例条目", "type": "pitfall",
          "domain": ["backend"], "scope": "project", "status": "accepted",
          "confidence": "verified", "created": "2026-11-14",
          "updated": "2026-11-14", "module": module}
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
```

（文件头补 `from pathlib import Path` 若 Task 1 未加。）

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py -q`
Expected: FAIL（`test_lint_rejects_module_non_string` 通过——schema 未约束 int；两个 accepts 用例通过）→ 即缺 schema 约束。若三个全过也继续 Step 3（约束是显式契约，不是可观察行为）。

- [ ] **Step 3: Write minimal implementation**

`src/kb/taxonomy.py` 的 `props` dict 中 `"superseded_by"` 行后加：

```python
        # repowiki 桥(spec 2026-11-14 §4.1): 条目 → repowiki 模块归属键, 缺省=不导出
        "module": {"type": ["string", "null"]},
```

`schema/frontmatter.schema.json` 的 `"properties"` 中同步加（保持既有缩进 4 空格）：

```json
    "module": {
      "type": ["string", "null"]
    },
```

- [ ] **Step 4: Run test to verify it passes + 全量 lint 回归**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py tests/test_lint.py -q`
Expected: PASS。再跑 `.venv/Scripts/python.exe -m kb.cli lint --scope agent-kb --repo .`（仓根）确认存量零新增错误。

- [ ] **Step 5: Commit**

```bash
git add src/kb/taxonomy.py schema/frontmatter.schema.json tests/test_repowiki.py
git commit -m "feat(repowiki): front-matter 新增可选 module 归属字段"
```

---

### Task 3: repowiki 根定位 + 模块树加载 + 条目归属分组

**Files:**
- Modify: `src/kb/repowiki.py`
- Test: `tests/test_repowiki.py`（追加）

**Interfaces:**
- Consumes: Task 1 全部原语；`kb.entry` 的 `iter_entry_paths`/`parse_entry`。
- Produces:
  - `find_repowiki_root(repo: Path, explicit: str | Path | None = None) -> Path | None`
  - `project_root_of(repo: Path) -> Path`
  - `load_module_tree(repowiki_root: Path, lang: str) -> tuple[dict, Path] | None`（目录缺失→None；schema 守卫/YAML 坏→`ValueError`）
  - `module_dir(locale_dir: Path, modules: dict, module_path: str) -> Path`
  - `group_entries(repo_root: Path) -> tuple[dict[str, list], list[str]]`（module→Entry 列表，未归属 id 列表；跳过 draft 与无 id）

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_repowiki.py`：

```python
from kb import repowiki


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
    assert repowiki.find_repowiki_root(tmp_path / "missing").parent == tmp_path


def test_find_repowiki_root_explicit_and_missing(tmp_path):
    zh = _tree(tmp_path)
    root = tmp_path / ".qoder" / "repowiki"
    assert repowiki.find_repowiki_root(tmp_path, explicit=str(root)) == root
    assert repowiki.find_repowiki_root(tmp_path, explicit=str(tmp_path / "nope")) is None
    (tmp_path / "bare").mkdir()
    assert repowiki.find_repowiki_root(tmp_path / "bare") is None


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
```

文件头补 `import pytest`。

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py -q`
Expected: FAIL（`AttributeError: module 'kb.repowiki' has no attribute 'find_repowiki_root'`）

- [ ] **Step 3: Write minimal implementation**

`src/kb/repowiki.py` 追加：

```python
from pathlib import Path

import yaml

from kb.entry import iter_entry_paths, parse_entry


def find_repowiki_root(repo: Path, explicit: str | Path | None = None) -> Path | None:
    """定位 repowiki 根(含 knowledge/ 目录)。自动探测支持两种布局: 载体即项目根、
    载体是项目根下的 kb 目录(如 docs/)的同级布局。"""
    if explicit is not None:
        p = Path(explicit)
        return p if (p / "knowledge").is_dir() else None
    repo = Path(repo)
    for cand in (repo / ".qoder" / "repowiki",
                 repo.parent / ".qoder" / "repowiki"):
        if (cand / "knowledge").is_dir():
            return cand
    return None


def project_root_of(repo: Path) -> Path:
    """导出默认落点 <项目根>/.qoder/repowiki 的项目根判定。"""
    repo = Path(repo)
    for cand in (repo, repo.parent):
        if (cand / ".git").exists() or (cand / ".qoder").exists():
            return cand
    return repo


def load_module_tree(repowiki_root: Path, lang: str) -> tuple[dict, Path] | None:
    """读 knowledge/<lang>/_index.yaml → (modules, locale_dir)。

    目录缺失 → None(静默跳过); schema_version 不符 / YAML 坏 / 缺 modules 段
    → ValueError(格式漂移守卫, 调用方决定警告跳过还是致命)。
    """
    locale_dir = Path(repowiki_root) / "knowledge" / lang
    idx = locale_dir / "_index.yaml"
    if not idx.exists():
        return None
    data = yaml.safe_load(idx.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{idx}: YAML 根非 mapping")
    if data.get("schema_version", SCHEMA_VERSION) != SCHEMA_VERSION:
        raise ValueError(
            f"{idx}: schema_version={data.get('schema_version')} 不受支持"
            f"(本工具按 {SCHEMA_VERSION} 解析)")
    modules = data.get("modules")
    if not isinstance(modules, dict):
        raise ValueError(f"{idx}: 缺 modules 段")
    return modules, locale_dir


def module_dir(locale_dir: Path, modules: dict, module_path: str) -> Path:
    """module_path('root' 或 'a/b') → 磁盘目录; 逐级取 dir_name, 未知段报错。"""
    root_meta = modules.get("root")
    if root_meta is None or "dir_name" not in root_meta:
        raise ValueError("模块树缺 root.dir_name")
    out = Path(locale_dir) / root_meta["dir_name"]
    if module_path == "root":
        return out
    prefix = ""
    for seg in module_path.split("/"):
        prefix = seg if not prefix else f"{prefix}/{seg}"
        meta = modules.get(prefix)
        if meta is None or "dir_name" not in meta:
            raise ValueError(f"模块树缺 {prefix}.dir_name")
        out = out / meta["dir_name"]
    return out


def group_entries(repo_root: Path) -> tuple[dict[str, list], list[str]]:
    """条目按 fm.module 归属分组; draft 永不导出(红线 1), 未归属计入警告清单。"""
    by_module: dict[str, list] = {}
    unassigned: list[str] = []
    for p in iter_entry_paths(repo_root):
        e = parse_entry(p)
        fm = e.fm
        if not fm.get("id") or fm.get("status") == "draft":
            continue
        mod = fm.get("module")
        if isinstance(mod, str) and mod.strip():
            by_module.setdefault(mod.strip(), []).append(e)
        else:
            unassigned.append(fm["id"])
    return by_module, unassigned
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kb/repowiki.py tests/test_repowiki.py
git commit -m "feat(repowiki): repowiki 根定位/模块树加载/条目归属分组"
```

---

### Task 4: export_repowiki（渲染 + overlay + skeleton + dry-run/write + 覆盖保护）

**Files:**
- Modify: `src/kb/repowiki.py`
- Test: `tests/test_repowiki.py`（追加）

**Interfaces:**
- Consumes: Task 1/3 全部；`kb.fskit.write_text_lf`；`kb.entry._first_sentence`（Task 6 用，这里先不用）。
- Produces:
  - `render_card(entries: list, type_card: dict[str, str]) -> str`
  - `git_head(root: Path) -> tuple[str, str]`
  - `export_repowiki(repo: Path, *, lang: str = "zh", out: str | Path | None = None, modules: str | Path | None = None, write: bool = False, force: bool = False, type_card: dict[str, str] | None = None) -> dict`
  - report 形状：`{"mode": "overlay"|"skeleton", "out": str, "planned"|"written": [str...], "unassigned": [str...], "warnings": [str...]}`

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_repowiki.py`：

```python
from kb import repowiki
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py -q`
Expected: FAIL（`ImportError: cannot import name 'export_repowiki'`）

- [ ] **Step 3: Write minimal implementation**

`src/kb/repowiki.py` 追加：

```python
import datetime as dt
import json
import subprocess

from kb.fskit import write_text_lf


def render_card(entries: list, type_card: dict[str, str]) -> str:
    """managed 卡正文: TOOL_MARKER 指纹 + 按 type 分节的条目投影(标题+summary+id)。"""
    by_type: dict[str, list] = {}
    for e in entries:
        if type_card.get(e.fm.get("type", "")):
            by_type.setdefault(e.fm["type"], []).append(e)
    if not by_type:
        return TOOL_MARKER + "\n\n（本模块暂无相关沉淀）\n"
    order = list(type_card)
    lines = [TOOL_MARKER, ""]
    for t in sorted(by_type, key=lambda t: order.index(t)):
        lines.append(f"## {TYPE_SECTION_TITLES.get(t, t)} ({t})")
        for e in by_type[t]:
            lines.append(f"- **{e.fm.get('title', '')}** — "
                         f"{e.summary()}（{e.fm['id']}）")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def git_head(root: Path) -> tuple[str, str]:
    """(commit, branch); 非 git 目录/命令缺失 → 空串(导出照常, 头字段留空)。"""
    def _rev(*args: str) -> str:
        try:
            out = subprocess.run(["git", "-C", str(root), *args],
                                 capture_output=True, text=True, timeout=10)
            return out.stdout.strip() if out.returncode == 0 else ""
        except OSError:
            return ""
    return _rev("rev-parse", "HEAD"), _rev("rev-parse", "--abbrev-ref", "HEAD")


def _load_modules_yaml(path: Path) -> dict:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("modules"), dict):
        raise ValueError(f"{path}: 需含 modules: 段(同 _index.yaml 形状)")
    return data["modules"]


def _module_yaml_update(mdir: Path, module_path: str, title: str,
                        existing: dict | None) -> str:
    """overlay 保留原生 kk_cards/kk_module_id; managed 卡换确定性 UUID。"""
    data = dict(existing or {})
    data.setdefault("schema_version", SCHEMA_VERSION)
    data["module_path"] = module_path
    data["title"] = data.get("title") or title
    for k in ("scope", "source_files", "depends_on", "related_to"):
        data.setdefault(k, [])
    data["kk_module_id"] = data.get("kk_module_id") or stable_uuid(module_path)
    cards = dict(data.get("kk_cards") or {})
    for card in MANAGED_CARDS:
        cards[card] = {"id": stable_uuid(f"{module_path}:{card}"),
                       "title": (cards.get(card) or {}).get("title") or title}
    data["kk_cards"] = cards
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def export_repowiki(repo: Path, *, lang: str = "zh",
                    out: str | Path | None = None,
                    modules: str | Path | None = None,
                    write: bool = False, force: bool = False,
                    type_card: dict[str, str] | None = None) -> dict:
    """条目 → .qoder/repowiki 投影。默认 dry-run; write=True 才落盘。

    overlay 模式读已有 _index.yaml 模块树(保留原生卡), skeleton 模式由 --modules
    清单从零建骨架。managed 卡(架构设计/特殊配置与命令)已存在且无本工具标记时
    视为外部内容: dry-run 记 warning, write 需 --force 否则 ValueError。
    """
    repo = Path(repo)
    tc = {**DEFAULT_TYPE_CARD, **(type_card or {})}
    root = Path(out) if out else project_root_of(repo) / ".qoder" / "repowiki"
    locale_dir = root / "knowledge" / lang

    mode = "overlay"
    try:
        loaded = load_module_tree(root, lang)
    except ValueError:
        raise  # schema 漂移/YAML 坏: 导出侧致命, 不猜
    if loaded is not None:
        modules_map, locale_dir = loaded
        idx_data = yaml.safe_load(
            (locale_dir / "_index.yaml").read_text(encoding="utf-8"))
    else:
        if modules is None:
            raise FileNotFoundError(
                f"{locale_dir}: 无已有 _index.yaml, 需 --modules <yaml> 提供模块清单")
        mode = "skeleton"
        modules_map = _load_modules_yaml(Path(modules))
        if "root" not in modules_map:
            raise ValueError("--modules 清单缺 root 模块")
        idx_data = {"schema_version": SCHEMA_VERSION,
                    "locale": "zh-CN" if lang == "zh" else lang,
                    "modules": modules_map}

    by_module, unassigned = group_entries(repo)
    commit, branch = git_head(project_root_of(repo))
    idx_data["commit"] = commit
    idx_data["branch"] = branch
    idx_data["exported_at"] = dt.datetime.now(dt.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")

    plan: list[tuple[Path, str]] = []
    warnings: list[str] = []
    for module_path in sorted(modules_map):
        meta = modules_map[module_path]
        title = meta.get("title", module_path)
        entries = by_module.get(module_path, [])
        mdir = module_dir(locale_dir, modules_map, module_path)
        existing_my: dict | None = None
        my_path = mdir / "_module.yaml"
        if my_path.exists():
            existing_my = yaml.safe_load(my_path.read_text(encoding="utf-8")) or {}
        plan.append((my_path,
                     _module_yaml_update(mdir, module_path, title, existing_my)))
        for card in MANAGED_CARDS:
            content = render_card(entries, tc)
            f = mdir / CARD_FILES[card]
            if f.exists() and TOOL_MARKER not in f.read_text(encoding="utf-8"):
                warnings.append(
                    f"{f}: 已有非本工具生成内容, 导入即替换语义下将被 kb 投影覆盖"
                    f"(再导出请带 force)")
                if write and not force:
                    raise ValueError(
                        f"{f}: 拒绝覆盖非本工具生成的 managed 卡(需 force)")
            plan.append((f, content))

    idx_path = locale_dir / "_index.yaml"
    plan.append((idx_path, yaml.safe_dump(idx_data, allow_unicode=True,
                                          sort_keys=False)))

    if write:
        for f, content in plan:
            f.parent.mkdir(parents=True, exist_ok=True)
            write_text_lf(f, content)
    rel = sorted(str(p.relative_to(root)) for p, _ in plan)
    report = {"mode": mode, "out": str(root),
              ("written" if write else "planned"): rel,
              "unassigned": sorted(unassigned), "warnings": warnings}
    if not write and warnings:
        report["warnings"] = warnings
    return report
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py -q`
Expected: PASS（含新增 9 用例）

- [ ] **Step 5: Commit**

```bash
git add src/kb/repowiki.py tests/test_repowiki.py
git commit -m "feat(repowiki): export_repowiki overlay/skeleton 投影导出(dry-run 默认)"
```

---

### Task 5: CLI 接线 `kb repowiki export`

**Files:**
- Modify: `src/kb/cli.py`（parser 区约 121 行 `p_init` 之前加子命令；dispatch 区约 283 行 `if args.cmd == "init"` 之前加分支）
- Test: `tests/test_repowiki.py`（追加）

**Interfaces:**
- Consumes: `export_repowiki`（Task 4）。
- Produces: CLI 语法 `kb repowiki export --repo <载体> [--lang zh] [--out P] [--modules F] [--write] [--force]`；退出码 0=成功（report 含 warnings 也 0），1=ValueError/FileNotFoundError（经 `main` 既有处理器）。

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_repowiki.py`：

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py::test_cli_repowiki_export_dry_run -q`
Expected: FAIL（`SystemExit: 2`——argparse 不认识 repowiki）

- [ ] **Step 3: Write minimal implementation**

`src/kb/cli.py`：
1. 顶部 import 区加 `from kb.repowiki import export_repowiki`（放在 `from kb.promote import promote` 后）。
2. parser 区（`p_init = sub.add_parser("init", ...)` 之前）加：

```python
    # repowiki 桥(spec 2026-11-14): 仿 trace 的组+子命令双层结构(组本身不带 common)
    p_rw = sub.add_parser("repowiki")
    rw_sub = p_rw.add_subparsers(dest="rw_cmd", required=True)
    p_rwe = rw_sub.add_parser("export", parents=[common])
    p_rwe.add_argument("--lang", default="zh")
    p_rwe.add_argument("--out", default=None,
                       help="repowiki 根目录, 默认 <项目根>/.qoder/repowiki")
    p_rwe.add_argument("--modules", default=None,
                       help="模块清单 yaml(无已有 _index.yaml 时必填)")
    p_rwe.add_argument("--write", action="store_true", help="落盘(默认 dry-run)")
    p_rwe.add_argument("--force", action="store_true",
                       help="覆盖非本工具生成的 managed 卡")
```

3. dispatch 区（`if args.cmd == "init":` 之前）加：

```python
    if args.cmd == "repowiki":
        if args.rw_cmd == "export":
            report = export_repowiki(repo, lang=args.lang, out=args.out,
                                     modules=args.modules, write=args.write,
                                     force=args.force)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py tests/test_cli.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kb/cli.py tests/test_repowiki.py
git commit -m "feat(repowiki): kb repowiki export 子命令(dry-run 默认)"
```

---

### Task 6: L2 侧车索引 build_sidecar + `kb index` 接线

**Files:**
- Modify: `src/kb/repowiki.py`
- Modify: `src/kb/cli.py`（`index` 分支，约 322-333 行）
- Test: `tests/test_repowiki.py`（追加）

**Interfaces:**
- Consumes: `load_module_tree`/`module_dir`/`CARD_FILES`（Task 3/1）；`kb.entry._first_sentence`；`kb.fskit.write_text_lf`。
- Produces:
  - `build_sidecar(repo: Path, repowiki_root: Path | None = None) -> Path | None`——写 `<repo>/kb/index.repowiki.jsonl`，返回路径；无 repowiki 根→None；schema 漂移语言目录跳过（打印 warning 到 stderr）。
  - 侧车记录形状：`{"kind": "repowiki_card", "id": "repowiki://<lang>/<module_path>/<card>", "module_path", "card", "title", "summary", "path", "locale"}`，其中 `path` 为相对 `--repo` 载体的 posix 路径（同级布局下形如 `../.qoder/repowiki/...`）。

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_repowiki.py`：

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py::test_build_sidecar_missing_tree_returns_none -q`
Expected: FAIL（`ImportError: cannot import name 'build_sidecar'`）

- [ ] **Step 3: Write minimal implementation**

`src/kb/repowiki.py` 追加：

```python
import os
import sys

from kb.entry import _first_sentence


def build_sidecar(repo: Path, repowiki_root: Path | None = None) -> Path | None:
    """扫描 repowiki 全部语言目录 → 侧车 kb/index.repowiki.jsonl(L2 检索面)。

    无 repowiki 根 → None(静默); 某语言目录 _index.yaml 坏/schema 漂移 → 打
    stderr warning 并跳过该目录(其余语言照常)——侧车是增强面, 不阻断 index 主流程。
    """
    repo = Path(repo)
    root = repowiki_root or find_repowiki_root(repo)
    if root is None or not (root / "knowledge").is_dir():
        return None
    records: list[dict] = []
    for lang_dir in sorted((root / "knowledge").iterdir()):
        if not lang_dir.is_dir():
            continue
        try:
            loaded = load_module_tree(root, lang_dir.name)
        except ValueError as exc:
            print(f"warning: repowiki sidecar: {exc}", file=sys.stderr)
            continue
        if loaded is None:
            continue
        modules, locale_dir = loaded
        for module_path in modules:
            meta = modules[module_path]
            try:
                mdir = module_dir(locale_dir, modules, module_path)
            except ValueError as exc:
                print(f"warning: repowiki sidecar: {exc}", file=sys.stderr)
                continue
            card_titles: dict = {}
            myaml = mdir / "_module.yaml"
            if myaml.exists():
                data = yaml.safe_load(myaml.read_text(encoding="utf-8")) or {}
                card_titles = data.get("kk_cards") or {}
            for card, fname in CARD_FILES.items():
                f = mdir / fname
                if not f.exists():
                    continue
                text = f.read_text(encoding="utf-8")
                body = "\n".join(
                    ln for ln in text.splitlines()
                    if ln.strip() and not ln.strip().startswith("#")
                    and ln.strip() != TOOL_MARKER).strip()
                summary = _first_sentence(body)[:120] if body else ""
                title = (card_titles.get(card) or {}).get("title") \
                    or meta.get("title", "")
                records.append({
                    "kind": "repowiki_card",
                    "id": f"{REPOWIKI_ID_PREFIX}{lang_dir.name}/"
                          f"{module_path}/{card}",
                    "module_path": module_path, "card": card, "title": title,
                    "summary": summary,
                    "path": Path(os.path.relpath(f, repo)).as_posix(),
                    "locale": lang_dir.name,
                })
    out = repo / "kb" / SIDECAR_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    write_text_lf(out, "".join(json.dumps(r, ensure_ascii=False) + "\n"
                               for r in records))
    return out
```

`src/kb/cli.py`：
1. import 区加 `from kb.repowiki import build_sidecar, export_repowiki`（合并 Task 5 那行）。
2. `index` 分支（`md, jl, dj = build_indexes(...)` 处）改为：

```python
        md, jl, dj = build_indexes(repo, repo_name=repo_name)
        print(f"wrote {md}\nwrote {jl}\nwrote {dj}")
        side = build_sidecar(repo)
        if side:
            print(f"wrote {side}")
        return 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py tests/test_index.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kb/repowiki.py src/kb/cli.py tests/test_repowiki.py
git commit -m "feat(repowiki): index.repowiki.jsonl 侧车索引 + kb index 接线"
```

---

### Task 7: 三层检索（layers `between` 注入 + search_sidecar + CLI search）

**Files:**
- Modify: `src/kb/layers.py`（`search_layers_report`）
- Modify: `src/kb/repowiki.py`
- Modify: `src/kb/cli.py`（`search` 分支）
- Test: `tests/test_repowiki.py`（追加）

**Interfaces:**
- Consumes: 侧车（Task 6）；`kb.search._hit`（复用 AND/CJK 2-gram 匹配）。
- Produces:
  - `search_sidecar(repo: Path, *, query: str | None = None) -> tuple[list[dict], dict]`——返回**未截断**命中行 + 死因报告（恒等式 `rejected.filter + rejected.query + len(matched) == scanned`）；行含 `kind: "repowiki_card"` 与 `id`（`repowiki://…`）。
  - `make_repowiki_layer(repo: Path)` → 可调对象 `(take: int, *, type=None, domain=None, tag=None, query=None) -> tuple[list[dict], dict]`；kb 专属过滤器（type/domain/tag）对 repowiki 层不适用，忽略。
  - `layers.search_layers_report(..., between=None)`——`between` 插在**第一层 kb 之后**；None 时行为逐字节不变。

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_repowiki.py`：

```python
from kb.layers import search_layers_report
from kb.repowiki import make_repowiki_layer, search_sidecar
from kb.index import build_indexes


def _layer_setup(tmp_path):
    """项目层零命中 + repowiki 层命中 + agent-kb 层命中, 验证优先级与截断。"""
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
             "created": "2026-11-14", "updated": "2026-11-14"},
            allow_unicode=True, sort_keys=False)
        + "---\n\n# Redis 连接超时排查\n\n正文。\n", encoding="utf-8")
    build_indexes(docs, repo_name="demo")
    export_repowiki(docs, write=True)  # 无 module 归属 → 卡片为占位内容
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py::test_search_sidecar_matches_query -q`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: Write minimal implementation**

`src/kb/repowiki.py` 追加：

```python
from kb.search import _hit


def search_sidecar(repo: Path, *, query: str | None = None
                   ) -> tuple[list[dict], dict]:
    """侧车 L2 检索: query 空白分词 AND 匹配 title/summary/module/card。

    恒等式 rejected.filter + rejected.query + len(matched) == scanned。
    无侧车 → 空结果零扫描(三层检索自然降级)。返回**未截断**行, 截断由 layers 层做。
    """
    jl = Path(repo) / "kb" / SIDECAR_NAME
    if not jl.exists():
        return [], {"scanned": 0, "rejected": {"filter": 0, "query": 0},
                    "matched": []}
    recs = [json.loads(x) for x in jl.read_text(encoding="utf-8").splitlines()
            if x.strip()]
    tokens = query.lower().split() if query else []
    matched: list[dict] = []
    n_no_hit = 0
    for rec in recs:
        fields: list[str] = []
        spans: list[list[int]] = []
        if tokens:
            parts = [("title", rec["title"].lower()),
                     ("summary", rec["summary"].lower()),
                     ("module", rec["module_path"].lower()),
                     ("card", rec["card"].lower())]
            fields, spans, hit_tokens = _hit(parts, tokens)
            if hit_tokens != set(tokens):
                n_no_hit += 1
                continue
        matched.append({**rec, "hit_fields": fields, "hit_spans": spans,
                        "score": 1.0})
    report = {"scanned": len(recs),
              "rejected": {"filter": 0, "query": n_no_hit},
              "matched": [{"id": r["id"], "hit_fields": r["hit_fields"],
                           "hit_spans": r["hit_spans"], "score": 1.0,
                           "rank": i + 1} for i, r in enumerate(matched)]}
    return matched, report


def make_repowiki_layer(repo: Path):
    """三层检索中层(project kb → repowiki → agent-kb), 供 layers between 注入。

    kb 专属过滤器(type/domain/tag)对 repowiki 卡不适用, 本层忽略; 行不限长,
    截断与 taken/report 归一由 search_layers_report 统一处理。
    """
    repo = Path(repo)

    def layer(take: int, *, type=None, domain=None, tag=None, query=None):
        return search_sidecar(repo, query=query)

    return layer
```

`src/kb/layers.py`：`search_layers_report` 签名加 `between=None`，函数体循环改为按"层序列"遍历：

```python
def search_layers_report(repos: list[Path], *, type=None, domain=None, tag=None,
                         scope=None, status=None, confidence=None, query=None,
                         limit: int = 10, between=None) -> tuple[list[dict], list[dict]]:
    """双层合并检索 + 逐层死因报告(供 trace)。repos 顺序即优先级, 逐层取满即截断。

    between(可选): 插入第一层 kb 与剩余层之间的中间层(如 repowiki), 签名
    (take, *, type, domain, tag, query) -> (rows, report), rows 不限长由本函数
    截断; None 时行为与旧版逐字节一致。
    （原有 limit 契约 docstring 保留不动）
    """
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 10
    limit = max(0, min(limit, 100))
    out: list[dict] = []
    reports: list[dict] = []
    seq: list[tuple[str, object]] = [("kb", rp) for rp in repos]
    if between is not None and seq:
        seq = seq[:1] + [("repowiki", None)] + seq[1:]
    for kind, rp in seq:
        if limit <= 0:  # 零名额: 不扫后端, 空 report 也要保持恒等式可用
            reports.append({"repo": "repowiki" if kind == "repowiki" else _name(rp),
                            "scanned": 0,
                            "rejected": {"filter": 0, "query": 0},
                            "matched": [], "taken": 0,
                            "truncated_at_limit": False})
            continue
        take = max(0, limit - len(out))
        if kind == "repowiki":
            rows, rep = between(take, type=type, domain=domain, tag=tag,
                                query=query)
            chosen = rows[:take]
            rep.update({"repo": "repowiki", "taken": len(chosen),
                        "truncated_at_limit": len(chosen) < len(rows)})
            reports.append(rep)
            out.extend(chosen)
            continue
        rows, rep = evaluate(rp, type=type, domain=domain, tag=tag, scope=scope,
                             status=status, confidence=confidence, query=query)
        chosen = rows[:take]
        by_id = {m["id"]: m for m in rep["matched"]}
        for r in chosen:
            m = by_id.get(r["id"])
            if m:
                r["hit_fields"] = m["hit_fields"]
                r["hit_spans"] = m["hit_spans"]
        rep.update({"repo": _name(rp), "taken": len(chosen),
                    "truncated_at_limit": len(chosen) < len(rows)})
        reports.append(rep)
        out.extend(chosen)
    return out[:limit], reports
```

（实现时对照 `git diff` 确认：仅签名加参 + 循环体改 seq 遍历，打分/命中透传/报告字段逻辑原样保留。）

`src/kb/cli.py` `search` 分支：`search_layers_report(...)` 调用前加中层注入：

```python
        between = None
        if (repo / "kb" / "index.repowiki.jsonl").exists() \
                and find_repowiki_root(repo):
            between = make_repowiki_layer(repo)
        res, reports = search_layers_report(
            layers_list, type=args.type, domain=args.domain, tag=args.tag,
            scope=args.scope, status=args.status, confidence=args.confidence,
            query=args.query, limit=args.limit, between=between)
```

import 区改为 `from kb.repowiki import (build_sidecar, export_repowiki, find_repowiki_root, make_repowiki_layer)`。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py tests/test_search.py tests/test_layers.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kb/layers.py src/kb/repowiki.py src/kb/cli.py tests/test_repowiki.py
git commit -m "feat(repowiki): kb search 三层命中(project→repowiki→agent-kb)"
```

---

### Task 8: L3 读原文（get_card_by_id + `kb show`）

**Files:**
- Modify: `src/kb/repowiki.py`
- Modify: `src/kb/cli.py`（`show` 分支）
- Test: `tests/test_repowiki.py`（追加）

**Interfaces:**
- Consumes: `find_repowiki_root`/`load_module_tree`/`module_dir`/`CARD_FILES`/`REPOWIKI_ID_PREFIX`。
- Produces: `get_card_by_id(repo: Path, card_id: str) -> str | None`——解析 `repowiki://<locale>/<module_path>/<card>`，读卡原文。

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_repowiki.py`：

```python
from kb.repowiki import get_card_by_id


def test_get_card_by_id_roundtrip(tmp_path):
    root, zh, rdir, ddir = _full_tree(tmp_path)
    docs = _docs_with_entries(tmp_path)
    export_repowiki(docs, write=True)
    text = get_card_by_id(docs, "repowiki://zh/docker_infra/architecture_design")
    assert text is not None and text.startswith(repowiki.TOOL_MARKER)
    assert "kb-20261114-c001" in text
    assert get_card_by_id(docs, "repowiki://zh/root/overview") == "原生概述内容。\n"


def test_get_card_by_id_bad_inputs(tmp_path):
    _full_tree(tmp_path)
    docs = tmp_path / "docs"
    assert get_card_by_id(docs, "kb-20261114-c001") is None  # 非 repowiki id
    assert get_card_by_id(docs, "repowiki://zh/root/no_such_card") is None
    assert get_card_by_id(docs, "repowiki://en/root/overview") is None  # 无 en 目录


def test_cli_show_repowiki_card(tmp_path, capsys):
    root, zh, rdir, ddir = _full_tree(tmp_path)
    docs = _docs_with_entries(tmp_path)
    export_repowiki(docs, write=True)
    rc = _dispatch(["show", "--repo", str(docs), "--agent-kb", "x",
                    "repowiki://zh/root/overview"]) \
        if False else _dispatch(
            ["show", "--repo", str(docs),
             "repowiki://zh/root/overview"])
    assert rc == 0
    assert capsys.readouterr().out == "原生概述内容。\n"


def test_cli_show_repowiki_not_found(tmp_path, capsys):
    _full_tree(tmp_path)
    docs = tmp_path / "docs"
    assert _dispatch(["show", "--repo", str(docs),
                      "repowiki://zh/root/overview"]) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py::test_get_card_by_id_bad_inputs -q`
Expected: FAIL（`ImportError`）

- [ ] **Step 3: Write minimal implementation**

`src/kb/repowiki.py` 追加：

```python
def get_card_by_id(repo: Path, card_id: str) -> str | None:
    """repowiki://<locale>/<module_path>/<card> → 卡原文 markdown。"""
    if not card_id.startswith(REPOWIKI_ID_PREFIX):
        return None
    rest = card_id[len(REPOWIKI_ID_PREFIX):]
    locale, _, tail = rest.partition("/")
    module_path, _, card = tail.rpartition("/")
    if not locale or not module_path or card not in CARD_FILES:
        return None
    root = find_repowiki_root(Path(repo))
    if root is None:
        return None
    try:
        loaded = load_module_tree(root, locale)
    except ValueError:
        return None
    if loaded is None:
        return None
    modules, locale_dir = loaded
    f = module_dir(locale_dir, modules, module_path) / CARD_FILES[card]
    return f.read_text(encoding="utf-8") if f.exists() else None
```

`src/kb/cli.py` `show` 分支最前面加：

```python
    if args.cmd == "show":
        if args.id.startswith(REPOWIKI_ID_PREFIX):
            text = get_card_by_id(repo, args.id)
            if text is None:
                print(f"not found: {args.id}", file=sys.stderr)
                return 1
            print(text)
            return 0
        if args.agent_kb:
            ...
```

import 区加 `get_card_by_id, REPOWIKI_ID_PREFIX`（并入既有 from kb.repowiki import 行）。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py tests/test_query.py -q`
Expected: PASS

注意：上面测试里 `test_cli_show_repowiki_card` 的 `if False else` 是笔误样板，实现时写成单次 `_dispatch(["show", "--repo", str(docs), "repowiki://zh/root/overview"])` 调用即可。

- [ ] **Step 5: Commit**

```bash
git add src/kb/repowiki.py src/kb/cli.py tests/test_repowiki.py
git commit -m "feat(repowiki): kb show 读 repowiki 卡原文(repowiki:// id)"
```

---

### Task 9: MCP 面接线（kb_search 三层 + kb_get 前缀解析）

**Files:**
- Modify: `src/kb/mcp_server.py`（`kb_search` 与 `kb_get` 两个 tool）
- Test: `tests/test_repowiki.py`（追加，复用 test_mcp.py 的 `_call`/`create_connected_server_and_client_session` 模式）

**Interfaces:**
- Consumes: `make_repowiki_layer`/`find_repowiki_root`/`get_card_by_id`/`REPOWIKI_ID_PREFIX`。
- Produces: MCP `kb_search` 在侧车存在且 repowiki 根可定位时自动三层；`kb_get` 支持 `repowiki://` id 返回卡原文；既有 kb 条目行为不变。

- [ ] **Step 1: Write the failing test**

追加到 `tests/test_repowiki.py`：

```python
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from kb.mcp_server import build_server

pytestmark = [pytest.mark.asyncio]


async def _mcp_call(server, name, args):
    async with create_connected_server_and_client_session(server) as client:
        res = await client.call_tool(name, args)
        text = res.content[0].text
        return res.isError, (json.loads(text) if text.startswith(("{", "["))
                             else text)


async def test_mcp_search_three_layers(tmp_path):
    docs, agent = _layer_setup(tmp_path)
    (agent / "kb" / "index.jsonl").write_text("", encoding="utf-8")
    srv = build_server(docs, agent_kbs=[agent], repo_name="demo")
    err, out = await _mcp_call(srv, "kb_search", {"query": "原生概述"})
    assert err is False
    assert out[0]["kind"] == "repowiki_card"
    assert out[0]["id"] == "repowiki://zh/root/overview"


async def test_mcp_get_repowiki_card(tmp_path):
    root, zh, rdir, ddir = _full_tree(tmp_path)
    docs = _docs_with_entries(tmp_path)
    export_repowiki(docs, write=True)
    srv = build_server(docs, repo_name="demo")
    err, out = await _mcp_call(
        srv, "kb_get", {"id": "repowiki://zh/docker_infra/architecture_design"})
    assert err is False
    assert "kb-20261114-c001" in out
```

（文件已有 `pytestmark` 冲突时——本文件此前无 pytestmark——保留本行即可；若与既有 mark 重复，合并为单条列表。）

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py::test_mcp_search_three_layers -q`
Expected: FAIL（kb_search 只回 kb 层命中/零命中 hint，无 repowiki 行）

- [ ] **Step 3: Write minimal implementation**

`src/kb/mcp_server.py`：
1. import 区加：

```python
from kb.repowiki import (REPOWIKI_ID_PREFIX, find_repowiki_root,
                         get_card_by_id, make_repowiki_layer)
```

2. `kb_search` 中 `rows, reports = search_layers_report(...)` 调用改为：

```python
        between = None
        if (repo / "kb" / "index.repowiki.jsonl").exists() \
                and find_repowiki_root(repo):
            between = make_repowiki_layer(repo)
        rows, reports = search_layers_report(
            layers, type=type, domain=domain, tag=tag, scope=scope, query=query,
            limit=limit, between=between)
```

3. `kb_get` 函数体最前面（`got = None` 之前）加：

```python
        if id.startswith(REPOWIKI_ID_PREFIX):
            text = get_card_by_id(repo, id)
            if text is None:
                raise ValueError(f"not found: {id}")
            return text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/Scripts/python.exe -m pytest tests/test_repowiki.py tests/test_mcp.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kb/mcp_server.py tests/test_repowiki.py
git commit -m "feat(repowiki): MCP kb_search 三层命中 + kb_get 解析 repowiki:// id"
```

---

### Task 10: 真机实测（Qoder 导入验证）+ 文档回写

**Files:**
- Modify: `README.md`（Agent-KB 仓根，增"RepoWiki 桥"一节）
- Modify: `docs/superpowers/specs/2026-11-14-repowiki-bridge-design.md`（§6 风险表回填实测结论）
- 说明：四个业务仓的 AGENTS.md 一句话入口由用户决定后另提，不在本任务。

**Interfaces:**
- Consumes: Task 1-9 全部。

- [ ] **Step 1: 用真实项目库跑导出（验证最大未知项：Qoder 对自造 UUID 的容忍度）**

Run（Agent-KB 仓根）：
```bash
.venv/Scripts/python.exe -m kb.cli repowiki export --repo ../flysee-video-setting/docs --dry-run 2>&1 | head -40
```
（预期：mode=overlay 或报错"无 _index.yaml"——flysee-video-setting 尚无 repowiki 导出时属预期，改对 flysee_video_web 跑：）
```bash
.venv/Scripts/python.exe -m kb.cli repowiki export --repo ../flysee_video_web/docs --dry-run 2>&1 | head -40
```
核对：report 的 planned 文件清单只含 managed 卡 + `_module.yaml` + `_index.yaml`；warnings 为空或有明确覆盖提示。

- [ ] **Step 2: 给真实条目加 module 归属后全量导出**

先给 flysee-video-setting `docs/kb/` 中想进投影的条目加 `module: <module_path>`（module_path 取 flysee_video_web repowiki 的模块路径，如 `docker_infra`、`backend_services/upgrade_lifecycle`），然后：
```bash
.venv/Scripts/python.exe -m kb.cli index --repo ../flysee-video-setting/docs --repo-name flysee-video-setting
.venv/Scripts/python.exe -m kb.cli repowiki export --repo ../flysee-video-setting/docs --out ../flysee_video_web/.qoder/repowiki --write
.venv/Scripts/python.exe -m kb.cli index --repo ../flysee_video_web/docs
```
核对：`../flysee_video_web/docs/kb/index.repowiki.jsonl` 生成且含导出卡；`kb search --repo ../flysee_video_web/docs --query <条目关键词>` 三层命中 repowiki 行。

- [ ] **Step 3: Qoder IDE 人工导入验证（人工检查点，不可自动化）**

在 Qoder IDE 中对 flysee_video_web 执行"导入自 .qoder/repowiki"，观察：
1. 导入是否接受自造 `kk_module_id`/卡 UUID（不报错即耐受）；
2. 替换粒度是整模块还是按卡；
3. kb 投影内容是否出现在知识卡片中。

把结论回填进 `docs/superpowers/specs/2026-11-14-repowiki-bridge-design.md` §6 风险表第一行（"已实测：…"）。若导入拒绝自造 UUID，在 §6 追加降级结论（文件格式兼容 + Qoder 任务直接读文件）。

- [ ] **Step 4: 写 README 章节**

`README.md` 增一节（放"观测面板"类章节之后，位置以 README 现有结构为准）：

```markdown
## RepoWiki 桥

把项目知识投影为 Qoder RepoWiki 文件格式，并把 RepoWiki 纳入 kb 检索。

- `kb repowiki export --repo <载体> [--write] [--force]`：按条目 front-matter
  可选字段 `module: <module_path>` 归属，聚合进 `.qoder/repowiki/knowledge/zh/`
  的两类 managed 卡（架构设计/特殊配置与命令）。默认 dry-run；overlay 模式
  保留 Qoder 原生模块树与原生卡，只写 managed 卡。
- `kb index` 自动探测 `.qoder/repowiki` 生成侧车 `kb/index.repowiki.jsonl`；
  `kb search` 变三层（project kb → repowiki → agent-kb），结果带
  `kind: "repowiki_card"`；`kb show repowiki://<locale>/<module>/<card>`（MCP
  `kb_get` 同 id）读卡原文。
```

- [ ] **Step 5: 全量回归 + Commit**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: 全绿。

```bash
git add README.md docs/superpowers/specs/2026-11-14-repowiki-bridge-design.md
git commit -m "docs(repowiki): README 桥接章节 + Qoder 导入实测结论回填"
```

---

## Self-Review 记录

- **Spec 覆盖**：§4.1 module 字段→Task 2/3；§4.1 模块树双来源→Task 3/4；§4.2 投影渲染+文件名映射→Task 1/4；§4.3 默认映射+覆盖配置（`type_card` 参数留了覆盖口，`repowiki.yaml map:` 配置解析未做——spec 说"可用 repowiki.map 覆盖"，实现以 `type_card` 参数承载，YAML 配置入口留待真实需求，属 YAGNI 收敛）；§4.4 UUID→Task 1/4；§4.5 覆盖保护→Task 4；§5.1 侧车→Task 6；§5.2 三层+L3→Task 7/8/9；§5.3 容错→Task 3/6；§6 风险实测→Task 10；§7 测试→各任务。
- **占位符扫描**：无 TBD/TODO；Task 8 内注明一处测试样板笔误的修正写法。
- **类型一致性**：`search_layers_report` 新参 `between` 在 Task 7 定义、cli.py(Task 5/7) 与 mcp_server.py(Task 9) 消费，签名一致；`export_repowiki` 参数在 Task 4 定义、Task 5 消费一致；`get_card_by_id(repo, card_id)` Task 8 定义、Task 9 消费一致；侧车记录键 `kind/id/module_path/card/title/summary/path/locale` 在 Task 6 产出、Task 7/8 消费一致。
