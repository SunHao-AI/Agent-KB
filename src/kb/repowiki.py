# src/kb/repowiki.py
"""Agent-KB ↔ Qoder RepoWiki 双向桥(spec 2026-11-14)。

导出器把项目库条目按 `module` front-matter 归属聚合进 RepoWiki 的两类 managed 卡
(架构设计/特殊配置与命令), overlay 到 `.qoder/repowiki/knowledge/<lang>/`;
检索面经 `index.repowiki.jsonl` 侧车把 RepoWiki 卡纳入 kb search 三层命中。
"""
from __future__ import annotations

import uuid
from pathlib import Path

import yaml

from kb.entry import iter_entry_paths, parse_entry

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
