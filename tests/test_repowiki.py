# tests/test_repowiki.py
import uuid
from pathlib import Path

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
