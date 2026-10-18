---
id: kb-20261012-e664
title: FastAPI 静态段路由必须声明在 path-param 路由之前（literal 不自动胜出）
type: pitfall
domain:
- backend
tags:
- fastapi
- routing
- starlette
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-05'
updated: '2026-10-18'
review_by: '2027-01-16'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/权限与接口路由.md
---

# FastAPI 静态段路由必须声明在 path-param 路由之前（literal 不自动胜出）

## 背景 / 现象

> 面向：`flysee_video_web` 后端（FastAPI），适用于所有 Starlette 路由。

**现象**：`GET /v1/tasks/{task_id}` 已存在时再补 `GET /v1/tasks/stats/daily`，若后者声明在文件靠后位置，请求 `/v1/tasks/stats/daily` 会被 `{task_id}` 吞掉（`task_id="stats"`），返回"任务不存在"而不是统计数据。

## 根因

**根因**：Starlette 路由**按注册顺序**匹配，先注册者胜出——不存在"静态段优先于参数段"的自动优先级。Flask 的 werkzeug 有静态段加权，FastAPI 没有。

## 解决方案

**解决**：所有静态子路径（`/stats/daily`、`/images/{filename}` 等）路由必须在同 router 内**先于** `/{task_id}` 系列声明；code review 时按 router 文件内声明顺序核对一遍。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/backend/权限与接口路由.md` :: 「FastAPI 静态段路由必须声明在 path-param 路由之前（literal 不自动胜出）」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例





源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/backend/权限与接口路由.md` :: 「FastAPI 静态段路由必须声明在 path-param 路由之前（literal 不自动胜出）」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

