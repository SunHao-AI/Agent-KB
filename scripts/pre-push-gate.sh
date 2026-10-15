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
#
# 判定对象 = 被推 ref 的内容, 不是工作区 (2026-10-14 首验踩坑修正):
#   - lint 用 `git show <tip>:<file>` 喂 ruff stdin, 未提交的 WIP 不会污染判定;
#   - pytest/npm test 只能就地跑 (需 .venv 与 gitignore 的 .env, 临时 worktree 复现不了),
#     故先校验"测试面"在工作区与待推 tip 之间完全一致, 不一致直接拦截并给出可操作提示,
#     避免"跑的是工作区、推的是 HEAD"这种假绿/假红。
set -u

if [ "${PREPUSH_SKIP:-0}" = "1" ]; then
    echo "pre-push-gate: SKIPPED via PREPUSH_SKIP=1" >&2
    exit 0
fi

ROOT=$(git rev-parse --show-toplevel) || exit 1
cd "$ROOT" || exit 1

# ---- 单实例锁 (kb-20261015-bee9 根治): 同仓并发门禁会让多株 pytest 互踩共享 ----
# ---- SQLite 测试库, 产生随机瞬态失败误报。锁放 git-dir 下, mkdir 原子创建;    ----
# ---- 持锁进程已死(陈旧锁)才接管; PREPUSH_SKIP 提前退出, 不进锁不残留。        ----
GITDIR=$(git rev-parse --git-dir) || exit 1
GATE_LOCK="$GITDIR/pre-push-gate.lock"
if ! mkdir "$GATE_LOCK" 2>/dev/null; then
    other=$(cat "$GATE_LOCK/pid" 2>/dev/null)
    if [ -n "$other" ] && kill -0 "$other" 2>/dev/null; then
        echo "pre-push-gate: FAIL - 本仓已有门禁实例在跑 (pid $other), 拒绝并发。" >&2
        echo "  并发 pytest 会互踩测试库产生假红 (kb-20261015-bee9)。等其结束或用" >&2
        echo "  Get-CimInstance Win32_Process 匹配 pytest 确认后再推。" >&2
        echo "  确知旧门禁已僵死: Stop-Process -Id $other; 后重推 (陈旧锁会被自动接管)。" >&2
        exit 1
    fi
    echo "pre-push-gate: WARN - 发现陈旧锁 (pid=${other:-?} 已死), 接管" >&2
    rm -rf "$GATE_LOCK" 2>/dev/null
    mkdir "$GATE_LOCK" || {
        echo "pre-push-gate: FAIL - 陈旧锁接管失败, 请手工删除 $GATE_LOCK 后重推。" >&2
        exit 1
    }
fi
echo $$ > "$GATE_LOCK/pid"
trap 'rm -rf "$GATE_LOCK"' EXIT INT TERM

# stdin (ref 行) 只有一份, 先缓冲下来复用
refs=$(cat)

# 待推 tip 清单 (删除 ref 的全 0 sha 不算)
ZERO="0000000000000000000000000000000000000000"
tips=$(printf '%s\n' "$refs" | awk '{print $2}' | grep -v "^${ZERO}$" | sort -u)

# 测试面一致性: pytest/npm test 只能就地跑, 若工作区的测试相关文件与待推 tip 不一致,
# 就地跑出来的结果不代表被推内容 → 拦下并给可操作处置, 不做"假绿"放行。
# 只看测试面 (py/config 或 js 源), 前端 WIP、文档 WIP 不阻塞 push。
assert_test_face_clean() {
    [ -n "$tips" ] || return 0
    dirty=""
    for t in $tips; do
        d=$(git diff --name-only "$t" -- "$@" 2>/dev/null) || continue
        dirty="$dirty
$d"
    done
    dirty=$(printf '%s\n' "$dirty" | sed '/^$/d' | sort -u)
    # 未跟踪的同类文件会改变就地跑的收集结果, 只提示不拦截 (临时脚本很常见)
    untracked=$(git ls-files --others --exclude-standard -- "$@" 2>/dev/null | sed '/^$/d')
    [ -n "$dirty" ] || return 0
    echo "pre-push-gate: FAIL - 工作区测试面与待推内容不一致, 就地跑的测试不代表被推内容。" >&2
    printf '%s\n' "$dirty" | sed 's/^/    /' >&2
    [ -n "$untracked" ] && {
        echo "  (另: 未跟踪的同类文件也会参与就地跑, 仅供确认)" >&2
        printf '%s\n' "$untracked" | sed 's/^/    /' >&2
    }
    cat >&2 <<'HINT'
  处置(任选其一):
    a) 提交这批改动后重推:  git add -u; git commit -m "..."; git push
    b) 临时隔离 WIP 再推:   git stash push -m wip -- <上述文件>; git push; git stash pop
    c) 确知与测试无关:      $env:PREPUSH_SKIP='1'; git push   (跳过整套门禁)
HINT
    exit 1
}

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
    assert_test_face_clean src package.json package-lock.json
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

# ---- 收集本次 push 涉及的 .py (增量 lint 范围, 记 "tip<TAB>file" 便于按被推内容取正文) ----
py_pairs=""
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
    for f in $files; do
        py_pairs="$py_pairs
$local_sha	$f"
    done
done <<EOF
$refs
EOF

# ---- 1. 增量 lint 硬门禁 (F + E9) —— 判定对象是被推 tip 里的正文, 不是工作区 ----
changed=$(printf '%s\n' "$py_pairs" | sed '/^[ \t]*$/d' | cut -f2 | sort -u)
lint_fail=0
if [ -n "$changed" ]; then
    if "$VENV_PY" -m ruff --version >/dev/null 2>&1; then
        n=$(printf '%s\n' "$changed" | wc -l | tr -d ' ')
        echo "pre-push-gate: ruff check --select F,E9 (增量 ${n} 个 .py, 取被推 ref 内容) ..." >&2
        for f in $changed; do
            # 取该文件最后一次出现的 tip 正文 (多 tip 时以最后一个为准, 常规单 tip 无歧义)
            tip=$(printf '%s\n' "$py_pairs" | sed '/^[ \t]*$/d' | awk -F'\t' -v F="$f" '$2==F {t=$1} END{print t}')
            [ -n "$tip" ] || continue
            content=$(git show "$tip:$f" 2>/dev/null) || continue   # 本次 push 内已删除 → 不查
            if ! printf '%s\n' "$content" | "$VENV_PY" -m ruff check --select F,E9 \
                    --stdin-filename "$f" - ; then
                lint_fail=1
            fi
        done
        if [ "$lint_fail" -ne 0 ]; then
            echo "pre-push-gate: FAIL - 增量 lint 未过 (F/E9 真错误类, 已按被推内容判定)。修复后重新 commit 再 push, 或 PREPUSH_SKIP=1 应急跳过。" >&2
            exit 1
        fi
    else
        echo "pre-push-gate: WARN - venv 缺 ruff, 增量 lint 跳过 (pytest 仍硬门禁)" >&2
    fi
else
    echo "pre-push-gate: 本次 push 无 .py 变更, 跳过增量 lint" >&2
fi

# ---- 2. 全量 pytest 硬门禁 + 3. coverage 报告 (不设阈值) ----
# 就地跑前先确认测试面与工作区一致 (pytest 收集 tests/, 受后端源码与配置影响)
assert_test_face_clean '*.py' pyproject.toml pytest.ini setup.cfg tox.ini conftest.py
echo "pre-push-gate: pytest 全量 (coverage 报告: ${COV_TARGET}, 无阈值) ..." >&2
# shellcheck disable=SC2086
"$VENV_PY" -m pytest -q $COV_ARGS || {
    echo "pre-push-gate: FAIL - 测试未过, 禁止 push。修复后重试, 或 PREPUSH_SKIP=1 应急跳过。" >&2
    exit 1
}

echo "pre-push-gate: PASS (lint 增量 + pytest 全量 + coverage 报告)" >&2
exit 0
