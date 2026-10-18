---
id: kb-20261012-e6e1
title: 新增 npm 依赖未安装到容器 node_modules 卷
type: pitfall
domain:
- frontend
tags:
- npm
- docker
- vite
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/构建工具与开发流程.md
---

# 新增 npm 依赖未安装到容器 node_modules 卷

## 背景 / 现象

浏览器控制台报 `net::ERR_ABORTED` 与 `TypeError: Failed to fetch dynamically imported module`，Vite 容器日志显示 `Failed to resolve import "jszip" from "src/components/ModelUpload.vue"`。

## 根因

前端容器用命名卷 `frontend_node_modules` 隔离 node_modules，新增依赖（如 `jszip`）写入 package.json 后未在容器内执行 `npm install`，导致模块解析失败，进而引发 HMR 加载中断。

## 解决方案

新增 npm 依赖后，需在容器内安装：`docker exec -w /app flysee-video-setting-frontend npm install`（或重启前端容器触发安装）。排查时用 `docker exec ... ls /app/node_modules/<pkg>` 确认依赖是否已安装。

## 验证

（自本条方案段提取）`docker exec ... ls /app/node_modules/<pkg>` 能列出该包目录即依赖已装；页面不再报模块解析错误。

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->

## 参考

- 源记录: `docs/known-pitfalls/frontend/构建工具与开发流程.md`
