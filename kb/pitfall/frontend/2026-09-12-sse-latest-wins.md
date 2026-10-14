---
id: kb-20261013-c6e3
title: SSE 静默重拉与手动查询的响应乱序覆盖：搜索"偶发失灵"（列表组件缺 latest-wins 守卫）
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-12'
updated: '2026-10-13'
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/SSE实时化与重连.md
---

# SSE 静默重拉与手动查询的响应乱序覆盖：搜索"偶发失灵"（列表组件缺 latest-wins 守卫）

## 背景 / 现象

浏览器实测：任务页填 task_id 前缀点「查询」，请求正确发出（`search=0e399a`，后端正确返回 `total=0/1`），但 8 秒后表格仍是全量 31 条。网络面板时间线是铁证：

```

[16] GET /v1/tasks                    ← SSE 初始重放触发 800ms 防抖静默重拉

[17] GET /v1/tasks?...&search=0e399a  ← 用户点查询, 先回(结果正确)

```

[17] 先回写入过滤结果，[16] 这个**更早发出、更晚返回**的无 search 请求后回，把全量覆盖回去。

## 根因

`fetchTasks` 有 **4 个触发源**：SSE 事件防抖静默重拉、查询按钮、翻页、URL appId watch。任何两路在途交错都可能"旧响应晚到"（SSE 事件恰在点查询时到达 / dev 环境 uvicorn reload 拉长响应时间都会放大窗口）。函数只写状态、**不校验响应是否还对应"当前意图"**——典型的 last-write-wins-on-arrival（按到达顺序覆盖）而非 latest-wins-on-issue（按发出顺序取最新）。

## 解决方案

抽纯函数 `createResponseGuard()`（task-query.js，latest-wins 单调序号）并接入 `fetchTasks` 三处：

```js

const seq = tasksResponseGuard.next()          // 发出前领号

// 响应写回前:

if (!tasksResponseGuard.isLatest(seq)) return  // then 里: 过期结果丢弃

if (!tasksResponseGuard.isLatest(seq)) return  // catch 里: 过期失败不弹"加载失败"打扰

// finally 里: 只有最新请求才允许收 loading（过期请求不得关掉新请求的 loading）

```

## 验证

- 行为级复验（复刻竞态）：进页 1s 内（SSE 静默重拉在途）点查询 → 等 8s → 表格稳定"共 1 条"；修复前同场景被覆盖回"共 31 条"。护栏 `task-query.spec.js` J1–J3。

- **通用判据：列表/详情组件只要有 ≥2 个数据拉取触发源（轮询、SSE 推送重拉、手动查询、翻页、路由参数），拉取函数就必须带 latest-wins 守卫**。`catch` 和 `finally` 与写回同样要判过期——否则过期请求还会误弹错误提示、误关 loading。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/SSE实时化与重连.md` 「SSE 静默重拉与手动查询的响应乱序覆盖：搜索"偶发失灵"（列表组件缺 latest-wins 守卫）」
