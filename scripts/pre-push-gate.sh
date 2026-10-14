#!/bin/sh
# pre-push 最小工程门禁 (roadmap A6, 替代零 CI) — 本文件是唯一母本。
# 安装: 在目标仓根执行
#   powershell -NoProfile -ExecutionPolicy Bypass -File .agent-kb/scripts/install-gate.ps1
# (Agent-KB 仓自身: -File scripts/install-gate.ps1)
# 安装器把本文件复制到目标仓 .git/hooks/pre-push-gate.sh, 并生成 launcher 转发 stdin。
#
# 门禁构成:
#   0. 环境自检 (venv 缺失 / 缺 pytest → 失败模式清单, 喂给 B1 kb doctor)
#   1. 增量 lint 硬门禁: 仅查 push 范围内新增/修改的 .py, 规则收窄到 F + E9
#      (真错误类)。各仓全量 lint 存量欠账已挂账 (roadmap §6), 不做全仓硬门禁。
#   2. 全量 pytest 硬门禁: 失败即拦截 push (A6 验收标准)
#   3. coverage 报告: 只输出不设阈值 (无 --cov-fail-under)
#   Node 仓 (无 pyproject.toml 仅 package.json): npm test 硬门禁。
# 应急跳过: $env:PREPUSH_SKIP='1'; git push ...
set -u

if [ "${PREPUSH_SKIP:-0}" = "1" ]; then
    echo "pre-push-gate: SKIPPED via PREPUSH_SKIP=1" >&2
    exit 0
fi

ROOT=$(git rev-parse --show-toplevel) || exit 1
cd "$ROOT" || exit 1

# ---- 仓型探测: python(pyproject.toml) / node(package.json) ----
if [ -f pyproject.toml ]; then
    FLAVOR=python
elif [ -f package.json ]; then
    FLAVOR=node
else
    echo "pre-push-gate: 既无 pyproject.toml 也无 package.json, 跳过。" >&2
    exit 0
fi

if [ "$FLAVOR" = node ]; then
    command -v npm >/dev/null 2>&1 || { echo "pre-push-gate: FAIL - 未找到 npm" >&2; exit 1; }
    echo "pre-push-gate: npm test ..." >&2
    npm test --silent || {
        echo "pre-push-gate: FAIL - npm test 未过, 禁止 push。修复后重试, 或 PREPUSH_SKIP=1 应急跳过。" >&2
        exit 1
    }
    echo "pre-push-gate: PASS (npm test)" >&2
    exit 0
fi

# ---- python 仓 ----
VENV_PY=".venv/Scripts/python.exe"
[ -f "$VENV_PY" ] || VENV_PY=".venv/bin/python"
if [ ! -f "$VENV_PY" ]; then
    echo "pre-push-gate: FAIL - venv python 不存在 (.venv/ 未装配)" >&2
    exit 1
fi
"$VENV_PY" -c "import pytest" 2>/dev/null || {
    echo "pre-push-gate: FAIL - venv 缺 pytest (uv sync / pip install -e '.[dev]')" >&2
    exit 1
}

# coverage 被测包: 目录启发式 backend/ -> app/ -> src/<pkg>/ -> 仓根; 排除 egg-info 等构建产物
if [ -d backend ]; then
    COV_TARGET="backend"
elif [ -d app ]; then
    COV_TARGET="app"
elif [ -d src ]; then
    COV_TARGET=$(for d in src/*/; do
        b=$(basename "$d")
        case "$b" in *.egg-info|__pycache__) continue ;; esac
        echo "$b"; break
    done)
    [ -n "$COV_TARGET" ] || COV_TARGET="src"
else
    COV_TARGET="."
fi

# pytest-cov 缺失时降级为无 coverage 的裸 pytest (coverage 只是报告项, 不是门禁项)
COV_ARGS=""
"$VENV_PY" -c "import pytest_cov" 2>/dev/null && COV_ARGS="--cov=$COV_TARGET --cov-report=term"

# ---- 收集本次 push 涉及的 .py (增量 lint 范围) ----
ZERO="0000000000000000000000000000000000000000"
py_files=""
while read -r local_ref local_sha remote_ref remote_sha; do
    [ "$local_sha" = "$ZERO" ] && continue  # 删除远端 ref, 无新内容
    if [ "$remote_sha" = "$ZERO" ]; then
        # 新分支: 锚到 origin/master 的 merge-base; 锚不到则本次无增量可查
        base=$(git merge-base "$local_sha" origin/master 2>/dev/null) || base="$local_sha"
    else
        # force-push 后旧 tip 可能已不可达: merge-base 兜底
        base=$(git merge-base "$remote_sha" "$local_sha" 2>/dev/null) || base="$remote_sha"
    fi
    files=$(git diff --name-only "$base" "$local_sha" -- '*.py' 2>/dev/null) || continue
    py_files="$py_files
$files"
done

# ---- 1. 增量 lint 硬门禁 (F + E9) ----
changed=$(printf '%s\n' "$py_files" | sed '/^$/d' | sort -u)
to_lint=""
if [ -n "$changed" ]; then
    # 只保留工作区仍存在的文件 (本 push 内已删除的无需 lint); 仓内路径无空格, 单词拆分安全
    for f in $changed; do
        [ -f "$f" ] && to_lint="$to_lint $f"
    done
fi
if [ -n "$to_lint" ]; then
    if "$VENV_PY" -m ruff --version >/dev/null 2>&1; then
        n=$(printf '%s\n' "$changed" | wc -l | tr -d ' ')
        echo "pre-push-gate: ruff check --select F,E9 (增量 ${n} 个 .py) ..." >&2
        # shellcheck disable=SC2086
        "$VENV_PY" -m ruff check --select F,E9 $to_lint || {
            echo "pre-push-gate: FAIL - 增量 lint 未过 (F/E9 真错误类)。修复后再 push, 或 PREPUSH_SKIP=1 应急跳过。" >&2
            exit 1
        }
    else
        echo "pre-push-gate: WARN - venv 缺 ruff, 增量 lint 跳过 (pytest 仍硬门禁)" >&2
    fi
else
    echo "pre-push-gate: 本次 push 无 .py 变更, 跳过增量 lint" >&2
fi

# ---- 2. 全量 pytest 硬门禁 + 3. coverage 报告 (不设阈值) ----
echo "pre-push-gate: pytest 全量 (coverage 报告: ${COV_TARGET}, 无阈值) ..." >&2
# shellcheck disable=SC2086
"$VENV_PY" -m pytest -q $COV_ARGS || {
    echo "pre-push-gate: FAIL - 测试未过, 禁止 push。修复后重试, 或 PREPUSH_SKIP=1 应急跳过。" >&2
    exit 1
}

echo "pre-push-gate: PASS (lint 增量 + pytest 全量 + coverage 报告)" >&2
exit 0
