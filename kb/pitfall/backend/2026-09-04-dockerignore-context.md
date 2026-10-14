---
id: kb-20261013-9328
title: 前端镜像与后端镜像共用仓库根时，`.dockerignore` 作用域按 context 根独立
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: probable
created: '2026-09-04'
updated: '2026-10-13'
severity: medium
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/构建与开发环境.md
---

# 前端镜像与后端镜像共用仓库根时，`.dockerignore` 作用域按 context 根独立

## 背景 / 现象

> 面向：`flysee_video_web` 的 `frontend`（context = `frontend/`）与 `web-backend`（context = 仓库根）双服务 compose 布局。

## 根因

不会。Docker 读取的是 **build context 根目录下的 `.dockerignore`**，`frontend` 服务的 context 是 `frontend/`，用的是 `frontend/.dockerignore`（内含 `node_modules` / `dist` / `.vite`），与仓库根 `.dockerignore` 互不相干。

## 解决方案

多服务共享仓库时，改根 `.dockerignore` 前先用 `docker compose config` 或 compose 文件里的 `build.context` 确认每个服务的 context 边界，再判断影响范围。

## 验证

Docker 读取的是 build context 根目录下的 `.dockerignore`：`frontend` 服务的 context 是 `frontend/`，用的是 `frontend/.dockerignore`（内含 `node_modules` / `dist` / `.vite`），与仓库根 `.dockerignore` 互不相干。

## 适用边界

多服务共享仓库时，改根 `.dockerignore` 前先用 `docker compose config` 或 compose 文件里的 `build.context` 确认每个服务的 context 边界，再判断影响范围。
多服务共享仓库时，改根 `.dockerignore` 前先用 `docker compose config` 或 compose 文件里的 `build.context` 确认每个服务的 context 边界，再判断影响范围。

## 参考

- 源记录: `docs/known-pitfalls/backend/构建与开发环境.md` 「前端镜像与后端镜像共用仓库根时，`.dockerignore` 作用域按 context 根独立」
