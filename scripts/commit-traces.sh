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

if [ -z "$(git status --porcelain -- traces/)" ]; then
    echo "commit-traces: no trace changes"
    exit 0
fi

git add traces/
git commit -m "chore(traces): daily trace commit"
git push origin master
