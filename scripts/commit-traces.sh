#!/bin/sh
# 每日 traces 提交推送 (对应 schedule "Agent-KB 每日 traces 提交推送", 2026-11-07 重建)
# 口径: 只 add traces/ 与本次自身产生的提交, 绝不越界; 无变更空转; 推送走正常 pre-push 门禁,
#       严禁设置 PREPUSH_SKIP 绕过。失败即非 0 退出, 由调用方如实上报。
set -e

cd "$(dirname "$0")/.."

branch=$(git rev-parse --abbrev-ref HEAD)
if [ "$branch" != "master" ]; then
    echo "commit-traces: 当前分支为 $branch, 非 master, 拒绝执行" >&2
    exit 2
fi

# 周一顺带生成上一自然周快照(kb trace snapshot 幂等: 已存在则退 1, 此处只告警不重写)。
# 失败只告警绝不阻断每日提交: 快照是观测面的下游消费, 它坏了不该让 traces 账本停更
# —— 观测不拖垮任何事(与 serve 同款红线)。步骤须在 porcelain 空转检查之前,
# 否则"无新 trace 即 exit 0"会让快照永远不生成; 也须在 git add traces/ 之前才能进同一次提交。
if [ "$(date +%u)" = "1" ]; then
  # 本机 POSIX 布局无 .venv/bin/kb, Windows 上是 .venv/Scripts/kb.exe, 先探测后使用。
  KB_BIN=".venv/bin/kb"; [ -x "$KB_BIN" ] || KB_BIN=".venv/Scripts/kb.exe"
  if ! "$KB_BIN" trace snapshot --repo . >/dev/null 2>&1; then
    echo "commit-traces: ⚠ 周一快照生成失败(不阻断提交), 手动回补: kb trace snapshot --repo ." >&2
  fi
fi

if [ -z "$(git status --porcelain -- traces/)" ]; then
    echo "commit-traces: no trace changes"
    exit 0
fi

git add traces/
git commit -m "chore(traces): daily trace commit"
git push origin master
