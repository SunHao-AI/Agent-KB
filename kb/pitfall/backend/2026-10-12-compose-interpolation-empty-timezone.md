---
id: kb-20261012-b88a
title: compose 里 ${APP_TIMEZONE} 不带默认值会注入空串
type: pitfall
domain:
- backend
tags:
- compose
- interpolation
- timezone
- default-value
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-04'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/时区与容器.md
---

# compose 里 ${APP_TIMEZONE} 不带默认值会注入空串

## 背景 / 现象

> 面向：全工作区 4 仓库的 `docker-compose*.yml` `environment` 块。

**现象**：`environment: TZ=${APP_TIMEZONE}` 命中变量未声明（`.env` 中根本没有 `APP_TIMEZONE`）时，compose 插值返回**空串**而非报错——容器 `TZ=` 为空，glibc 退回默认 UTC，本应上海的日志和 `date` 又变 UTC，且 compose 不告警。

## 根因

**根因**：compose 变量插值只对形如 `${var:-default}` 给默认值；裸 `${var}` 在值缺失时插成空串。把 `APP_TIMEZONE` 误写成 `.env.example` 备注（未真正写值）、或新增仓库忘抄 `.env`，都会触发该回归。

## 解决方案

**解决**：**所有** compose 里的 `${APP_TIMEZONE...}` 一律写 `${APP_TIMEZONE:-Asia/Shanghai}` 带默认值——即使 `.env` 已声明这也是零成本兜底，`.env` 未声明该变量时也不破坏启动。新增 `environment:` 注入 TZ 时模板化复制，**禁止裸插值**。

## 验证

原文「现象」段实录: 变量未声明时 compose 插值返回空串而非报错、不告警——容器 `TZ=` 为空, glibc 退回默认 UTC, 本应上海的日志和 date 又变 UTC。

## 适用边界与反例

**预防**：
- 评审 `docker-compose*.yml` 时看到 `${APP_TIMEZONE` 先问"有没有 `:-` 默认"，缺默认直接打回；
- 新增仓库 `.env` 漏写 `APP_TIMEZONE` 时，默认值兜底会让容器行为与本机一致（仍上海），不引入静默回归。

## 参考

- 源记录: `docs/known-pitfalls/backend/时区与容器.md`
