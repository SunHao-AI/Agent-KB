"""门禁 COV_TARGET 启发式回归（0a8dc48, 2026-11-13）。

背景：母本 `scripts/pre-push-gate.sh` 的 coverage 目标此前取 `src/*/` 的 **basename**，
Agent-KB 仓根同时有 markdown 知识库 `kb/` 与 Python 包 `src/kb/`，`--cov=kb` 被
coverage 解析到前者（零 .py）→ 每次门禁刷 "No data was collected" +
"Failed to generate report" 两条假警告。修复 = 保留相对路径全串 `src/<pkg>`。

手法对齐 test_gate_base_anchor.py（I-9）：从**母本原文**按标记切出启发式代码段
（不复制粘贴，防测试与母本漂移），在 Git 自带 sh 上对八种仓型形状断言 COV_TARGET：
  1. 同名歧义仓根(kb/ + src/kb/) → src/kb   ← 0a8dc48 回归锚点
  2. backend 布局 → backend；3. backend+src 并存 → backend(优先级)；4. app 布局 → app
  5. 平铺仓(无三者) → .；6. src 下只有 egg-info 构建产物 → src(兜底)
  7. src 多包 → 字典序首包
  8. src 下无子目录(只有散落 .py) → src(兜底)  ← 六十二轮走查发现 glob 未匹配跑偏
sh.exe 或 git 缺失时整模块 skip（CI 与非 Windows 环境不假失败）。
"""

import os
import subprocess
from pathlib import Path

import pytest

from test_gate_base_anchor import GATE, _clean_env, _sh


def _cov_script(tmp_path: Path) -> Path:
    """从母本切出 COV_TARGET 启发式段, 包成可独立执行的探针脚本。

    起点 = `# coverage 被测包` 注释行, 终点 = `COV_ARGS=` 之前(不含)。
    标记丢失说明母本结构变了, 直接 fail 提醒同步本测试, 而不是静默测旧拷贝。
    """
    lines = GATE.read_text(encoding="utf-8").splitlines()
    try:
        start = next(i for i, l in enumerate(lines) if l.startswith("# coverage 被测包"))
        end = next(i for i, l in enumerate(lines) if l.startswith("COV_ARGS="))
    except StopIteration:
        pytest.fail("母本标记漂移: 找不到 '# coverage 被测包' 或 'COV_ARGS=' 段")
    body = "\n".join(lines[start:end])
    script = tmp_path / "cov-probe.sh"
    script.write_text(
        "#!/bin/sh\nset -u\n" + body + '\nprintf \'%s\\n\' "$COV_TARGET"\n',
        encoding="utf-8", newline="\n",
    )
    return script


def _run(script: Path, shape: Path) -> str:
    sh = _sh()
    r = subprocess.run(
        [sh, str(script)], capture_output=True, text=True,
        cwd=str(shape), env=_clean_env(os.path.dirname(sh)),
    )
    assert r.returncode == 0, r.stderr
    return r.stdout.strip()


@pytest.fixture()
def script(tmp_path: Path) -> Path:
    return _cov_script(tmp_path)


def _mk(tmp_path: Path, name: str, *dirs: str) -> Path:
    shape = tmp_path / name
    for d in dirs:
        (shape / d).mkdir(parents=True)
    return shape


def test_same_name_root_prefers_src_pkg(script, tmp_path):
    """0a8dc48 回归: 仓根 markdown kb/ 与 src/kb/ 同名, 必须给全路径 src/kb。"""
    shape = _mk(tmp_path, "agentkb", "kb", "src/kb")
    assert _run(script, shape) == "src/kb"


def test_backend_layout(script, tmp_path):
    shape = _mk(tmp_path, "backendrepo", "backend")
    assert _run(script, shape) == "backend"


def test_backend_wins_over_src(script, tmp_path):
    shape = _mk(tmp_path, "both", "backend", "src/pkg")
    assert _run(script, shape) == "backend"


def test_app_layout(script, tmp_path):
    shape = _mk(tmp_path, "apprepo", "app")
    assert _run(script, shape) == "app"


def test_flat_repo_falls_back_to_root(script, tmp_path):
    shape = _mk(tmp_path, "flat", "mypkg")
    assert _run(script, shape) == "."


def test_src_with_only_build_artifacts_falls_back_to_src(script, tmp_path):
    """src 下只有 egg-info/__pycache__: 全被跳过 → 兜底 src, 不能输出空串。"""
    shape = _mk(tmp_path, "srconly", "src/agent_kb.egg-info", "src/__pycache__")
    assert _run(script, shape) == "src"


def test_multi_pkg_takes_lexicographic_first(script, tmp_path):
    shape = _mk(tmp_path, "multi", "src/zzz", "src/aaa")
    assert _run(script, shape) == "src/aaa"


def test_src_without_subdirs_falls_back_to_src(script, tmp_path):
    """六十二轮走查: src 下只有散落 .py 时 glob 不匹配, sh 迭代字面量 `src/*`,
    旧实现会输出 `src/*` → coverage "Module src/* was never imported" 假警告。
    修复后必须落到兜底 src(目录级收集仍有效)。"""
    shape = _mk(tmp_path, "nosub", "src")
    (shape / "src" / "loose.py").write_text("x = 1\n", encoding="utf-8")
    assert _run(script, shape) == "src"
