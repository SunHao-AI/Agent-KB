---
id: kb-20261013-6aca
title: committed 代码 import 了未跟踪文件：本地全绿、干净检出必挂
type: pitfall
domain:
- frontend
tags: []
scope: universal
status: accepted
confidence: verified
created: '2026-09-21'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: medium
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/模块引用与提交完整性.md
---

# committed 代码 import 了未跟踪文件：本地全绿、干净检出必挂

## 背景 / 现象

任务启动功能分支上，`index.vue` / `detail.vue` 已提交且 `import { taskStatusText } from './task-status'`，但 `task-status.js` 一直是 `??` 未跟踪状态、从未进任何 commit 的 tree。本地 `npm test`（129 passed）与 GetDiagnostics 全绿，因为工作区恰好存在该文件；任何人干净检出后 `npm run build` / dev 启动直接 Vite `module not resolved` 构建失败。

## 根因

多任务流水线里，任务级评审只看「本任务 diff 是否正确」，实现与测试都基于工作区（脏）文件；引用一个"别人还没提交的模块"时没有任何环节校验它是否在 `git ls-files` 里。

## 解决方案

1. 修复：`git add frontend/src/views/tasks/task-status.js; git commit`（按路径精确 add，勿 `git add -A` 裹进无关 WIP）。

  2. 验证口径（提交视图类改动后必查一次）：

     ```powershell

     # committed 视图的相对 import 是否全部在 HEAD tree 里

     git grep -h "from '\./" HEAD -- frontend/src/views/tasks/index.vue

     git ls-tree HEAD --name-only frontend/src/views/tasks/

     ```

  3. 泛化规则：**功能分支合入前，对每个被改的入口文件核对相对依赖 ∈ HEAD**；本地测试绿只证明"工作区"可构建，不证明"提交"可构建。

## 验证

验证口径（提交视图类改动后必查一次）：`git grep -h "from '\./" HEAD -- frontend/src/views/tasks/index.vue` 与 `git ls-tree HEAD --name-only frontend/src/views/tasks/` 对账——committed 视图的相对 import 是否全部在 HEAD tree 里。

## 适用边界

跨任务共享的模块（工具/映射文件）要在**引入它的那个任务**里一并提交，而不是留给"以后某个任务"。

## 参考

- 源记录: `docs/known-pitfalls/frontend/模块引用与提交完整性.md` 「committed 代码 import 了未跟踪文件：本地全绿、干净检出必挂」
