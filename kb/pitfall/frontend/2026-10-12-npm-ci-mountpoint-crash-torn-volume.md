---
id: kb-20261012-95b3
title: 容器内 `npm ci` 确定性崩溃（Exit handler never called）致 node_modules 卷撕裂
type: pitfall
domain:
- frontend
tags:
- npm
- docker
- node_modules
- volume
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-22'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/构建工具与开发流程.md
---

# 容器内 `npm ci` 确定性崩溃（Exit handler never called）致 node_modules 卷撕裂

## 背景 / 现象

setting 前端是 dev 型容器（bind mount `frontend:/app` + 命名卷 `..._node_modules:/app/node_modules`，cmd `vite`）。`docker start` 后 vite 起不来：`Cannot find package '/app/node_modules/vite-plugin-pwa/index.js'`。进卷排查发现 **`vite-plugin-pwa` 目录为空、`node_modules/.bin` 整个缺失**，但 `node_modules` 有 472 个包目录——典型 npm 安装**中途崩溃被撕裂**（部分包落盘、bin 链接与收尾未做）。重跑反复以 `npm error Exit handler never called!` 退出；`npm rebuild` 能补回 `.bin` 但补不回被撕裂成空目录的包体。

## 根因

不是 WSL 内存/慢 I/O——是 **`npm ci` 第一步要 `rm -rf node_modules`，而它恰好是挂载卷的挂载点，容器内删不掉（Device or resource busy），npm 收尾处理器直接崩**（`Exit handler never called!`）。同一镜像构建期 `npm ci` 一直成功，因为那时 `/app/node_modules` 是普通目录。旁证：`npm install`（增量、不删目录）与 `npm rebuild` 都不崩。

## 解决方案

（两选一，均已实测）：
1. **overlay 安装 + 拷入卷**（恢复容器化跑法用）：`npm ci` 在容器可写层完成，再拷进卷，绕开"删挂载点"：
```powershell
docker run --rm -v flysee-video-setting_flysee-video-setting-node_modules:/mnt/nm `
  -v frontend\package.json:/app/package.json:ro -v frontend\package-lock.json:/app/package-lock.json:ro `
  -v frontend\.npmrc:/app/.npmrc:ro -w /app <前端镜像> `
  sh -c "rm -rf /mnt/nm/* && npm ci && cp -a /app/node_modules/. /mnt/nm/"
```
实测 691 包 2 分钟成功，`docker start` 后 vite 2.8s ready。（`/mnt/nm/*` 删内容不删挂载点本身。）
2. **宿主机 dev server**（bind mount 场景备用）：`docker stop` 容器，宿主 `npm run dev`（宿主 node_modules 完整），vite 代理 target 读根 `.env` 的 `FLYSEE_APP_PORT`。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

- **凡是把 `node_modules` 做成命名卷的 dev 容器，容器内永远不要跑 `npm ci`**（删不掉挂载点里的目录树时必崩）；增依赖用 `npm install <pkg>`（不删目录）或走上面路线 1。
- 前端 dev 容器起不来先分两层：**依赖树坏**（vite 报 Cannot find package / `.bin` 缺失）vs **代码坏**（vite 能起但运行报错）。判卷撕裂：`docker run --rm -v <卷>:/nm <镜像> sh -c "ls /nm/.bin | wc -l"`——容器 exited 时不能 `docker exec`，必须 `docker run --rm` 挂卷查。
- 与既有「容器 npm ci 报 Missing @esbuild from lock file」（同文件上一条）是两类问题：那条是**锁文件不一致**（npm 拒绝装），本条是**挂载点删不掉**（npm 自己崩）。

## 参考

- 源记录: `docs/known-pitfalls/frontend/构建工具与开发流程.md`
