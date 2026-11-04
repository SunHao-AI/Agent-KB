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
#   1.5 mypy 棘轮硬门禁 (仅配了 [tool.mypy] 的仓): 本次改到的 .py 必须零错,
#      存量不要求 (roadmap I-4b: web 仓试点 2026-11-03, 2026-11-04 归零后上提)。
#   2. 全量 pytest 硬门禁: 失败即拦截 push (A6 验收标准)
#   3. coverage 报告: 只输出不设阈值 (无 --cov-fail-under)
#   4. kb 库门禁: 本次 push 触碰 docs/kb(业务仓)或 kb/(Agent-KB)时, 对被推 tip
#      跑 kb lint --strict + kb index --check(临时 worktree 判定, 与 lint 同哲学),
#      防"改了知识忘重建索引"漂移 (2026-10-29 该漂移曾靠人眼发现)。
#   Node 仓 (无 pyproject.toml 仅 package.json): npm test 硬门禁。
#   混合仓 (pyproject.toml + frontend/package.json): python 门禁后再跑 frontend
#   的 npm test, 但仅当本次 push 触碰 frontend/ 才跑 (见 3.5 段)。
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

# stdin (ref 行) 只有一份, 先缓冲下来复用
refs=$(cat)

# 待推 tip 清单 (删除 ref 的全 0 sha 不算)
ZERO="0000000000000000000000000000000000000000"
tips=$(printf '%s\n' "$refs" | awk '{print $2}' | grep -v "^${ZERO}$" | sort -u)

# ---- I-9 (2026-11-04): 增量 base 锚点统一解析 --------------------------------
# 此前 lint / mypy / pytest / 前端 四段各抄一份"新分支锚 origin/master"的写法。
# 仓里没有 origin/master 时(web 仓只有 origin/main + origin/develop)merge-base 失败
# → base=local_sha → `git diff base..tip` 空 → 四段**静默整体跳过**, 只剩全量 pytest
# 照跑 = 新分支首推时增量 lint、mypy 棘轮、kb 门禁、前端门禁全部失明。
# 现在: 锚点按 origin/HEAD → origin/main → origin/master → 任一 origin/* 逐级探测;
# 全都探不到才退到**空树**(把全树当增量, 宁可全量判定也不放行), 并打 WARN 让退化可见。
# 空树 hash 用 `git hash-object -t tree /dev/null` 现取, 不硬编码字面量(跨 git 版本
# 稳妥)。注意必须把 /dev/null 当**文件参数**, 不能走 `</dev/null` 的 stdin: stdin 读
# 空内容时 `git hash-object` 什么都不输出且 rc=0(实测), 变量会成空串, 后续
# `git diff "" <tip>` 又退化成静默跳过 = 把 I-9 的兜底又打穿了。
FULL_TREE=$(git hash-object -t tree /dev/null 2>/dev/null)

# 锚点在**父作用域**探测一次(不是 resolve_base 内部): 该函数总被 $(...) 子 shell
# 调用, 内部赋值回不到父 shell, 探针会恒报 <none>、WARN 也会重复打印。
GATE_ANCHOR=""
for _cand in "$(git symbolic-ref -q refs/remotes/origin/HEAD 2>/dev/null)" \
             refs/remotes/origin/main refs/remotes/origin/master; do
    [ -n "$_cand" ] || continue
    git rev-parse --verify "${_cand}^{commit}" >/dev/null 2>&1 || continue
    GATE_ANCHOR="$_cand"
    break
done
if [ -z "$GATE_ANCHOR" ]; then
    # 无 origin/HEAD 且 main/master 都不存在: 取任一 origin/* 兜底。多分支时
    # merge-base 落到最近公共祖先, 增量范围只会偏大(偏严), 不会漏判。
    GATE_ANCHOR=$(git for-each-ref --format='%(refname)' refs/remotes/origin/ 2>/dev/null \
                  | grep -v '/HEAD$' | head -1)
fi
if [ -z "$GATE_ANCHOR" ] \
   && printf '%s\n' "$refs" | awk '{print $4}' | grep -q "^${ZERO}$"; then
    # 仅当本次 push 含新分支首推(远端 sha 全 0)时锚点缺失才有实际影响, 才 warn
    echo "pre-push-gate: WARN - 远端无可锚分支, 新分支首推的增量范围将退化为全树(偏严)" >&2
fi

# 输出: 本次增量 base 的 sha。
resolve_base() {
    rb_local="$1"; rb_remote="$2"
    if [ -n "$rb_remote" ] && [ "$rb_remote" != "$ZERO" ]; then
        # 常规推送: force-push 后旧 tip 可能已不可达, merge-base 兜底再退回旧 tip
        rb_b=$(git merge-base "$rb_remote" "$rb_local" 2>/dev/null) || rb_b="$rb_remote"
        printf '%s' "$rb_b"
        return 0
    fi
    if [ -n "$GATE_ANCHOR" ]; then
        rb_b=$(git merge-base "$rb_local" "$GATE_ANCHOR" 2>/dev/null) \
            || rb_b=$(git rev-parse "$GATE_ANCHOR" 2>/dev/null) || rb_b="$FULL_TREE"
    else
        rb_b="$FULL_TREE"
    fi
    printf '%s' "$rb_b"
}

# 诊断出口: $env:PREPUSH_GATE_PROBE='base'; git push ...  → 只报每个被推 ref 的锚点
# 与 base 就退出。用于人工核对"I-9 修完后我这个仓到底锚到哪", 也是 I-9 的测试面。
if [ "${PREPUSH_GATE_PROBE:-}" = "base" ]; then
    while read -r p_ref p_local p_rref p_remote; do
        [ -n "$p_local" ] || continue
        [ "$p_local" = "$ZERO" ] && continue
        p_base=$(resolve_base "$p_local" "$p_remote")
        printf 'probe: ref=%s remote_sha=%s anchor=%s base=%s\n' \
            "$p_ref" "$p_remote" "${GATE_ANCHOR:-<none>}" "$p_base"
    done <<PROBE
$refs
PROBE
    exit 0
fi

# ---- 单实例锁 (kb-20261015-bee9 根治): 同仓并发门禁会让多株 pytest 互踩共享 ----
# ---- SQLite 测试库, 产生随机瞬态失败误报。锁放 git-dir 下, mkdir 原子创建;    ----
# ---- 持锁进程已死(陈旧锁)才接管; PREPUSH_SKIP 提前退出, 不进锁不残留。        ----
# 取锁放在探针**之后**: 探针是只读诊断(不跑测试、不写工作区), 占锁既无必要, 又会
# 让诊断面被锁目录的建目录权限绑架 —— I-9 的测试在 hook 环境里就踩过: mkdir 报
# EACCES 导致 4 个用例集体 rc=1, 与要验证的锚点逻辑毫无关系。
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
kb_tips=""
while read -r local_ref local_sha remote_ref remote_sha; do
    [ "$local_sha" = "$ZERO" ] && continue  # 删除远端 ref, 无新内容
    base=$(resolve_base "$local_sha" "$remote_sha")
    files=$(git diff --name-only "$base" "$local_sha" -- '*.py' 2>/dev/null) || continue
    for f in $files; do
        py_pairs="$py_pairs
$local_sha	$f"
    done
    # kb 库是否被本次 push 触碰(业务仓 docs/kb, Agent-KB 自身 kb/) → 触发第 4 段
    if git diff --name-only "$base" "$local_sha" -- docs/kb kb/ 2>/dev/null | sed '/^$/d' | grep -q .; then
        kb_tips="$kb_tips
$local_sha"
    fi
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

# ---- 1.5 mypy 棘轮硬门禁 (roadmap I-4b, 2026-11-04 由 web 仓试点上提) ----
# 只对**配了 [tool.mypy] 的仓**生效(grep pyproject 判定): 没配 mypy 的仓直接跳过,
# 不会因为装了门禁就凭空多出一堵墙(实测 flysee 四仓仅 web 有此配置, media_server
# 是 node 仓更早就走 npm 分支)。
# 棘轮口径 = 只要求增量: 本次 push 改到的 .py 必须零错, 存量错误不要求(由各仓
# 分批清理消化)。哲学照抄第 1 段: 判定对象=被推 tip(临时 worktree, 与 kb 段同
# 构), 工具缺失只 WARN 不拦, 但真跑起来失败就硬拦。
# 关键坑(kb-20261103-a127): git-dir 在本脚本上方是按 `--git-dir` 取的**相对**路径,
# 而 worktree 的 .git 是文件不是目录 —— 相对 .git/xxx 当 --cache-dir 会让 mypy
# INTERNAL ERROR 崩溃, 崩溃输出里没有 "file:line: error:" 行, 被 grep 式判定读成
# 零错就是**假绿**。故此处另取 --absolute-git-dir, 且 rc>1 一律判 FAIL 不放行。
if [ -n "$changed" ] && grep -q '^\[tool\.mypy\]' pyproject.toml 2>/dev/null; then
    if "$VENV_PY" -m mypy --version >/dev/null 2>&1; then
        MYPY_GITDIR=$(git rev-parse --absolute-git-dir)
        mypy_wt="$MYPY_GITDIR/pre-push-gate.mypywt"
        rm -rf "$mypy_wt" 2>/dev/null
        mypy_tip=$(printf '%s\n' "$py_pairs" | sed '/^[ \t]*$/d' | awk -F'\t' '{print $1}' | tail -1)
        if git worktree add --detach "$mypy_wt" "$mypy_tip" >/dev/null 2>&1; then
            # cwd=worktree 根(路径与 git 输出口径一致), 配置与解释器都取自主仓绝对路径。
            # 输出落文件而非命令替换: 保证 mypy_rc 是 mypy 自己的退出码, 不会被
            # `cd && mypy` 里 cd 的失败码冒充(那会伪装成"有错但零 error 行"=假绿)。
            mypy_out_f="$MYPY_GITDIR/pre-push-gate.mypyout"
            ( cd "$mypy_wt" && "$ROOT/$VENV_PY" -m mypy "$COV_TARGET" \
                --config-file "$ROOT/pyproject.toml" \
                --cache-dir "$MYPY_GITDIR/pre-push-gate.mypycache" ) > "$mypy_out_f" 2>&1
            mypy_rc=$?
            git worktree remove --force "$mypy_wt" >/dev/null 2>&1
            # Windows 反斜杠转 / 以匹配 git 路径口径
            mypy_out=$(tr '\\' '/' < "$mypy_out_f"); rm -f "$mypy_out_f"
            if [ "$mypy_rc" -gt 1 ]; then
                echo "pre-push-gate: FAIL - mypy 异常退出 rc=$mypy_rc, 本次无法判定(不放行, 防假绿)。输出前 10 行:" >&2
                printf '%s\n' "$mypy_out" | head -10 | sed 's/^/    /' >&2
                echo "  修环境后重推, 或 PREPUSH_SKIP=1 应急跳过。" >&2
                exit 1
            fi
            # 输出格式合法性: mypy 只在 0/1 时必然打点行结论(Success / Found N errors)。
            # 两者都没有 = 根本没跑到 mypy(例如 cd 失败), 判不了就不放行。
            if ! printf '%s\n' "$mypy_out" | grep -qE '^(Success: no issues found|Found [0-9]+ error)'; then
                echo "pre-push-gate: FAIL - mypy 未给出可信结论(rc=$mypy_rc 但无 Success/Found 汇总行), 本次无法判定(不放行)。" >&2
                printf '%s\n' "$mypy_out" | head -10 | sed 's/^/    /' >&2
                exit 1
            fi
            if [ "$mypy_rc" -eq 0 ]; then
                echo "pre-push-gate: mypy 棘轮 PASS ($COV_TARGET 全仓零错)" >&2
            else
                mypy_fail=0
                for f in $changed; do
                    hits=$(printf '%s\n' "$mypy_out" | grep -E "^${f}:[0-9]+: error:" || true)
                    if [ -n "$hits" ]; then
                        printf '%s\n' "$hits" | sed 's/^/    /' >&2
                        mypy_fail=1
                    fi
                done
                if [ "$mypy_fail" -ne 0 ]; then
                    echo "pre-push-gate: FAIL - mypy 棘轮: 本次改动的 .py 必须零错(存量不要求)。" >&2
                    echo "  修复后重推, 或 PREPUSH_SKIP=1 应急跳过。" >&2
                    exit 1
                fi
                echo "pre-push-gate: mypy 棘轮 PASS (改动的 $(printf '%s\n' "$changed" | wc -l | tr -d ' ') 个 .py 零错)" >&2
            fi
        else
            echo "pre-push-gate: WARN - mypy 临时 worktree 创建失败, mypy 棘轮跳过(不假绿)" >&2
        fi
    else
        echo "pre-push-gate: WARN - 本仓配了 [tool.mypy] 但 venv 缺 mypy, 棘轮跳过。" >&2
        echo "  装配: uv sync --extra dev" >&2
    fi
fi

# ---- 4. kb 库硬门禁: 本次 push 触碰 docs/kb(业务仓)或 kb/(Agent-KB)时强制 ----
# ---- kb lint + index --check, 防"改了知识忘重建索引"的漂移(2026-10-29 靠 ----
# ---- 人眼才发现一次: 64e8 追加后 draft 索引混入未提交条目)。                ----
# 判定对象 = 被推 tip 的 kb 内容(导出到临时 worktree 跑), 工作区 WIP 不污染、
# 也不被波及(与 lint 段同哲学; 区别于 pytest 只能就地跑)。                    ----
# 解释器: 优先本仓 venv(kb 已随依赖装齐), 缺则退 Agent-KB 主仓 venv(同级约定)。
if [ -n "$(printf '%s\n' "$kb_tips" | sed '/^$/d')" ]; then
    KB_PY=""
    "$VENV_PY" -c "import kb" 2>/dev/null && KB_PY="$VENV_PY"
    if [ -z "$KB_PY" ]; then
        for cand in "../Agent-KB/.venv/Scripts/python.exe" "../Agent-KB/.venv/bin/python"; do
            [ -f "$cand" ] && "$cand" -c "import kb" 2>/dev/null && { KB_PY="$cand"; break; }
        done
    fi
    if [ -z "$KB_PY" ]; then
        echo "pre-push-gate: FAIL - 本次 push 触碰 kb 库, 但 kb 包不可用(本仓与 ../Agent-KB venv 均无)。" >&2
        echo "  装配: uv sync(本仓含 kb 依赖) 或确认同级 Agent-KB 主仓 .venv 存在。PREPUSH_SKIP=1 应急跳过。" >&2
        exit 1
    fi
    kb_tip=$(printf '%s\n' "$kb_tips" | sed '/^$/d' | tail -1)
    # 被推 tip 里没有 kb 库(如 feature 分支未带) → 无从校验, 跳过
    git ls-tree -d --name-only "$kb_tip" -- docs/kb kb 2>/dev/null | sed '/^$/d' | grep -q . || { echo "pre-push-gate: kb 门禁跳过(被推 tip 无 kb 库)"; kb_tip=""; }
    if [ -n "$kb_tip" ]; then
        kb_wt="$GITDIR/pre-push-gate.kbwt"
        rm -rf "$kb_wt" 2>/dev/null
        if git worktree add --detach "$kb_wt" "$kb_tip" >/dev/null 2>&1; then
            # 逐个校验存在的 kb 库(载体目录:lint scope)。Agent-KB 仓有两个库:
            # 根 kb/(agent-kb) 与 docs/kb/(project); 业务仓只有后者。
            # --repo-name 不参与猜测: repo 字段是**生成时**写进索引的值(业务仓
            # 用仓名, Agent-KB docs 库用 "docs"), 猜错 --check 恒 stale 误报 →
            # 直接从被推 tip 的 index.jsonl 首行自取, 与被检内容同源。
            kb_fail=0
            for lib in "docs:project" ".:agent-kb"; do
                kb_rel=${lib%%:*}; KB_SCOPE=${lib##*:}
                kb_repo="$kb_wt/$kb_rel"
                [ -f "$kb_repo/kb/index.jsonl" ] || continue
                KB_NAME=$(sed -n '1p' "$kb_repo/kb/index.jsonl" \
                          | sed -n 's/.*"repo"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')
                [ -n "$KB_NAME" ] || KB_NAME=$(basename "$kb_repo")
                echo "pre-push-gate: kb lint + index --check ($kb_rel/kb, tip ${kb_tip:0:8}, scope $KB_SCOPE, repo $KB_NAME) ..." >&2
                if ! "$KB_PY" -m kb.cli lint --scope "$KB_SCOPE" --strict --repo "$kb_repo"; then
                    echo "pre-push-gate: FAIL - kb lint 未过(被推内容, $kb_rel/kb)。修条目或按 kb 模板补齐后重推。" >&2
                    kb_fail=1
                fi
                if [ "$kb_fail" -eq 0 ] && ! "$KB_PY" -m kb.cli index --check --repo "$kb_repo" --repo-name "$KB_NAME"; then
                    echo "pre-push-gate: FAIL - kb 索引与被推内容漂移($kb_rel/kb)。修复: 仓根跑" >&2
                    echo "  ..\\Agent-KB\\.venv\\Scripts\\python.exe -m kb.cli index --repo $kb_rel --repo-name $KB_NAME" >&2
                    echo "  然后把 $kb_rel/kb/INDEX.md index.jsonl 一并提交。" >&2
                    kb_fail=1
                fi
            done
            git worktree remove --force "$kb_wt" >/dev/null 2>&1
            [ "$kb_fail" -eq 0 ] || exit 1
            echo "pre-push-gate: kb 门禁 PASS" >&2
        else
            echo "pre-push-gate: WARN - kb 临时 worktree 创建失败, kb 门禁跳过(不假绿)" >&2
        fi
    fi
fi

# ---- 2. 全量 pytest 硬门禁 + 3. coverage 报告 (不设阈值) ----
# 按改动范围跳过 (2026-11-03): 本次 push 不触碰后端代码/测试面时, 全量 pytest
# 跑的是与 push 无关的旧代码, 结果不反映本次改动 → 跳过, 与第 1 段增量 lint
# 只查 push 范围内 .py、第 3.5 段前端按 frontend/ 判定的哲学一致。纯 docs/、
# *.md、纯前端 push 不再空耗十几分钟全量后端测试 (此前每次约 15 分钟)。
py_touched=""
while read -r local_ref local_sha remote_ref remote_sha; do
    [ "$local_sha" = "$ZERO" ] && continue
    base=$(resolve_base "$local_sha" "$remote_sha")
    if git diff --name-only "$base" "$local_sha" -- '*.py' pyproject.toml pytest.ini setup.cfg tox.ini conftest.py 2>/dev/null | sed '/^$/d' | grep -q .; then
        py_touched=1
    fi
done <<EOF
$refs
EOF

if [ -z "$py_touched" ]; then
    echo "pre-push-gate: 本次 push 无后端代码/测试面变更, 跳过全量 pytest" >&2
else
    # 就地跑前先确认测试面与工作区一致 (pytest 收集 tests/, 受后端源码与配置影响)
    assert_test_face_clean '*.py' pyproject.toml pytest.ini setup.cfg tox.ini conftest.py
    echo "pre-push-gate: pytest 全量 (coverage 报告: ${COV_TARGET}, 无阈值) ..." >&2
    # shellcheck disable=SC2086
    "$VENV_PY" -m pytest -q $COV_ARGS || {
        echo "pre-push-gate: FAIL - 测试未过, 禁止 push。修复后重试, 或 PREPUSH_SKIP=1 应急跳过。" >&2
        exit 1
    }
fi

# ---- 3.5 python 仓内的前端子项目 (混合仓): frontend/ 有 package.json 时纳入门禁 ----
# 为什么单独一段: 仓型探测按 pyproject.toml 优先, 混合仓(后端 python + frontend/ 前端)
# 永远走 python 分支, node 分支的 npm test 永不触发 → 前端测试形同无门禁。
# (2026-10-30 flysee-video-setting 实测: 契约守护的 13 条 vitest 用例一次也不被 push 触发。)
# 沿用本门禁三条既有哲学:
#   a) 判定对象=被推内容: 仅当本次 push 触碰前端测试面才跑, 纯后端提交零成本;
#   b) 就地跑前校验测试面一致(否则跑的工作区/推的 HEAD, 假绿);
#   c) 工具/依赖缺失只 WARN 不拦(与"venv 缺 ruff 跳过 lint"同处理, 新克隆未 npm
#      install 不该阻塞 push), 但一旦真跑起来失败就硬拦。
if [ -f frontend/package.json ]; then
    fe_touched=""
    while read -r local_ref local_sha remote_ref remote_sha; do
        [ "$local_sha" = "$ZERO" ] && continue
        base=$(resolve_base "$local_sha" "$remote_sha")
        if git diff --name-only "$base" "$local_sha" -- frontend 2>/dev/null | sed '/^$/d' | grep -q .; then
            fe_touched=1
        fi
    done <<EOF
$refs
EOF

    if [ -z "$fe_touched" ]; then
        echo "pre-push-gate: frontend/ 未被本次 push 触碰, 前端测试跳过" >&2
    elif ! command -v npm >/dev/null 2>&1; then
        echo "pre-push-gate: WARN - 本次 push 改了 frontend/ 但未找到 npm, 前端测试跳过(不假绿)" >&2
    elif [ ! -d frontend/node_modules ]; then
        echo "pre-push-gate: WARN - frontend/node_modules 缺失, 前端测试跳过。" >&2
        echo "  跑前端测试请先: cd frontend; npm install" >&2
    else
        assert_test_face_clean frontend/package.json frontend/package-lock.json \
            frontend/vitest.config.js frontend/vite.config.js
        echo "pre-push-gate: frontend npm test ..." >&2
        ( cd frontend && npm test --silent ) || {
            echo "pre-push-gate: FAIL - 前端测试未过, 禁止 push。修复后重试, 或 PREPUSH_SKIP=1 应急跳过。" >&2
            exit 1
        }
        echo "pre-push-gate: frontend npm test PASS" >&2
    fi
fi

echo "pre-push-gate: PASS (lint 增量 + pytest 全量 + coverage 报告)" >&2
exit 0
