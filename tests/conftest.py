import pathlib
import pytest

SAMPLE_FRONTMATTER = """---
id: kb-20261012-7f3a
title: Vite HMR 在 Windows 下不生效
type: pitfall
domain: [frontend, build]
tags: [vite, hmr]
scope: stack
status: accepted
severity: medium
confidence: verified
created: 2026-10-12
updated: 2026-10-12
---

# Vite HMR 在 Windows 下不生效

## 背景 / 现象
第一段是摘要来源。

## 根因
机制说明。
"""


def make_entry(**over) -> str:
    fm = {
        "id": "kb-20261012-7f3a",
        "title": "demo",
        "type": "pitfall",
        "domain": ["frontend"],
        "scope": "project",
        "status": "draft",
        "confidence": "speculative",
        "created": "2026-10-12",
        "updated": "2026-10-12",
    }
    fm.update(over)
    head = "---\n" + "".join(f"{k}: {v}\n" for k, v in fm.items()) + "---\n"
    return head + "\n# " + str(fm["title"]) + "\n\n首段摘要。\n"


@pytest.fixture
def tmp_repo(tmp_path: pathlib.Path) -> pathlib.Path:
    (tmp_path / "kb").mkdir()
    return tmp_path
