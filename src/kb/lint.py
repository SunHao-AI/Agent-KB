from __future__ import annotations
from collections import Counter
from pathlib import Path
import re
import jsonschema
from kb.dedup import (MIN_FP_LEN, fingerprint, fingerprint_source, h2_sections,
                      normalize)
from kb.entry import parse_entry
from kb.taxonomy import load_taxonomy, derive_schema


# `kb index` 的生成物固定名, 不作为知识条目参与 lint
_GENERATED_NAMES = {"INDEX.md", "index.jsonl", "index.draft.jsonl"}

# 占位段检测用: 剥离 HTML 注释后判断段内容是否为空
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _placeholder_warnings(entry, sections: list[str]) -> list[str]:
    """该 type taxonomy sections 定义的每个 H2 段, 段内容剥离 HTML 注释后为空
    → 占位段回流, 返回不带 warning 前缀的提示列表(缺段不报, 只报"有段且为空")。

    段提取复用 dedup.h2_sections(H2 边界 + 围栏跳过), 与指纹提取同一实现。
    根因段文案保持既有 `placeholder root-cause section` 不变(兼容既有消费方),
    其余段文案为 `placeholder <段名> section`。
    """
    out: list[str] = []
    for header, content in h2_sections(entry):
        if _HTML_COMMENT_RE.sub("", content).strip():
            continue
        if "根因" in header:
            out.append("placeholder root-cause section")
        elif header in sections:
            out.append(f"placeholder {header} section")
    return out


def _iter_entries(root: Path):
    kb = Path(root) / "kb"
    if not kb.exists():
        return
    # 只遍历 kb 根第一层条目目录(kb/<type>/)再向下 rglob, 不进入 kb 根下
    # 挂载的子仓/子树(如 .agent-kb/), 避免扫入子仓生成物造成误报
    for d in sorted(p for p in kb.iterdir() if p.is_dir() and not p.name.startswith(".")):
        for p in sorted(d.rglob("*.md")):
            if p.name in _GENERATED_NAMES:
                continue
            yield parse_entry(p)


def lint_repo(repo_root: Path, scope: str = "project",
              cross_repos: list[Path] | None = None) -> list[str]:
    tax = load_taxonomy()
    schema = derive_schema(tax)
    validator = jsonschema.Draft202012Validator(schema)
    errors: list[str] = []
    entries = list(_iter_entries(repo_root))
    ids = {e.fm.get("id") for e in entries}
    id_counts = Counter(e.fm.get("id") for e in entries if e.fm.get("id"))
    for e in entries:
        rid = e.fm.get("id", e.path.name)
        if id_counts.get(e.fm.get("id"), 0) > 1:
            errors.append(f"{rid}: duplicate id {e.fm['id']}")
        for err in sorted(validator.iter_errors(e.fm), key=lambda x: x.json_path):
            errors.append(f"{rid}: schema {err.json_path}: {err.message}")
        if e.fm.get("scope") == "project" and scope == "agent-kb":
            errors.append(f"{rid}: scope=project must not live in agent-kb")
        if e.fm.get("scope") != "project" and scope == "project":
            errors.append(f"{rid}: scope!=project must be promoted to agent-kb")
        for f in ("related",):
            for ref in e.fm.get(f, []) or []:
                if ref not in ids:
                    errors.append(f"{rid}: {f} references missing {ref}")
        for f in ("supersedes", "superseded_by"):
            ref = e.fm.get(f)
            if ref and ref not in ids:
                errors.append(f"{rid}: {f} references missing {ref}")
        # H1 计数需跳过 ``` 围栏代码块: 块内以 "# " 开头的 shell/YAML 注释
        # 不是标题, 误计会迫使迁移侧改写代码块内容规避
        h1 = 0
        in_fence = False
        for ln in e.body.splitlines():
            if ln.strip().startswith("```"):
                in_fence = not in_fence
                continue
            if not in_fence and ln.strip().startswith("# "):
                h1 += 1
        if h1 != 1:
            errors.append(f"{rid}: expected exactly one H1, found {h1}")
        # 占位段回流防护: 该 type 存在模板定义的 H2 段(含根因段)但段内容
        # 剥离 HTML 注释后为空 → 仅 warning(占位段不阻断, 提示人工回填)
        type_sections = tax["types"].get(e.fm.get("type"), {}).get("sections", [])
        for msg in _placeholder_warnings(e, type_sections):
            errors.append(f"warning: {rid}: {msg}")
    # 指纹冲突检测: 规范化源短于 MIN_FP_LEN 不参检(防测试桩/占位段互撞),
    # 门槛常量唯一事实源在 kb.dedup
    fp_map: dict[str, list[str]] = {}
    for e in entries:
        rid = e.fm.get("id", e.path.name)
        src = normalize(fingerprint_source(e))
        if len(src) < MIN_FP_LEN:
            continue
        fp_map.setdefault(fingerprint(e), []).append(rid)
    for fp, rids in fp_map.items():
        for i in range(len(rids)):
            for j in range(i + 1, len(rids)):
                errors.append(f"{rids[i]}: duplicate fingerprint with {rids[j]}")
    for other in cross_repos or []:
        other_fps: dict[str, str] = {}
        for oe in _iter_entries(Path(other)):
            if len(normalize(fingerprint_source(oe))) >= MIN_FP_LEN:
                other_fps.setdefault(fingerprint(oe), oe.fm.get("id", oe.path.name))
        for e in entries:
            rid = e.fm.get("id", e.path.name)
            src = normalize(fingerprint_source(e))
            if len(src) < MIN_FP_LEN:
                continue
            oid = other_fps.get(fingerprint(e))
            if oid:
                errors.append(f"warning: {rid}: same fingerprint as {oid} in {Path(other).name}")
    return errors
