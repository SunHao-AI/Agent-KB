# src/kb/repowiki.py
"""Agent-KB ↔ Qoder RepoWiki 双向桥(spec 2026-11-14)。

导出器把项目库条目按 `module` front-matter 归属聚合进 RepoWiki 的两类 managed 卡
(架构设计/特殊配置与命令), overlay 到 `.qoder/repowiki/knowledge/<lang>/`;
检索面经 `index.repowiki.jsonl` 侧车把 RepoWiki 卡纳入 kb search 三层命中。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import yaml

from kb.entry import _first_sentence, iter_entry_paths, parse_entry
from kb.fskit import write_text_lf

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
    try:
        data = yaml.safe_load(idx.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"{idx}: YAML 解析失败: {e}") from e
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


def render_card(entries: list, type_card: dict[str, str], card: str) -> str:
    """managed 卡正文: TOOL_MARKER 指纹 + 按 type 分节的条目投影(标题+summary+id)。

    只收 type_card 路由到本卡(card)的条目; 路由不到的 type 不进本卡。
    """
    by_type: dict[str, list] = {}
    for e in entries:
        t = e.fm.get("type", "")
        if type_card.get(t) == card:
            by_type.setdefault(t, []).append(e)
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
    if existing is not None and not isinstance(existing, dict):
        raise ValueError(
            f"{mdir}/_module.yaml: 根非 mapping(YAML 合法但结构不符), 拒绝覆写")
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
                    modules: str | Path | None = None, write: bool = False,
                    force: bool = False,
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
            content = render_card(entries, tc, card)
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
    return report


def build_sidecar(repo: Path, repowiki_root: Path | None = None) -> Path | None:
    """扫描 repowiki 全部语言目录 → 侧车 kb/index.repowiki.jsonl(L2 检索面)。

    无 repowiki 根 → None(静默); 某语言目录 _index.yaml 坏/schema 漂移 → 打
    stderr warning 并跳过该目录(其余语言照常); 模块级损坏(_module.yaml 语法坏/
    顶层非 mapping/kk_cards 或 meta 非 mapping) → 打 stderr warning 并跳过该模块
    (其余模块照常)——侧车是增强面, 不阻断 index 主流程。
    全部语言目录均无果(无记录)时不写空侧车, 返回 None。
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
            except (ValueError, yaml.YAMLError, AttributeError) as exc:
                # 模块级损坏(YAML 语法坏/顶层非 mapping/kk_cards 非 mapping/
                # _index.yaml meta 非 mapping)只跳过该模块: 侧车是增强面,
                # 不阻断 index 主流程。
                print(f"warning: repowiki sidecar: {exc}", file=sys.stderr)
                continue
    if not records:
        return None
    out = repo / "kb" / SIDECAR_NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    write_text_lf(out, "".join(json.dumps(r, ensure_ascii=False) + "\n"
                               for r in records))
    return out
