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
