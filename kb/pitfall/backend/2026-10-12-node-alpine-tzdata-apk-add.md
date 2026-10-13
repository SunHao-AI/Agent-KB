---
id: kb-20261012-ebf1
title: node:20-alpine 缺 tzdata，注入 TZ 前必须先 apk add
type: pitfall
domain:
- backend
tags:
- alpine
- tzdata
- dockerfile
- node
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-04'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/时区与容器.md
---

# node:20-alpine 缺 tzdata，注入 TZ 前必须先 apk add

## 背景 / 现象

> 面向：`flysee-video-setting` prod / frontend / 本仓任何 `node:20-alpine` 镜像。

**现象**：按 plan 注入 `TZ=Asia/Shanghai` 后，node 容器 `date` 不切时区，或 `new Date().toString()` 仍返回 UTC（带 `Z` 后缀）。

## 根因

**根因**：`node:20-alpine` 基于 busybox，**不捆绑 tzdata**（与 `python:3.12-slim`、`mysql:8.0` 等自带不同；Debian / RHEL base 镜像与 Alpine 默认态不同）。`TZ` 环境变量需要 OS 层 `/usr/share/zoneinfo/<IANA>` 字典解析，Alpine 上裸 `TZ=Asia/Shanghai` 会无法读字典，Node 运行时继续回退 UTC。

## 解决方案

**解决**：

## 验证

原文「验证」段: `docker run --rm <image> date` 期望含 `+0800`/`CST`; 或 `docker exec <c> node -e "console.log(new Date().toString())"` 期望含 `GMT+0800`; media_server 已按 Dockerfile 内置方案落地。

- **验证**：`docker run --rm <image> date` 期望含 `+0800` / `CST`；或 `docker exec <c> node -e "console.log(new Date().toString())"` 期望含 `GMT+0800`。

## 适用边界与反例

- **Dockerfile 内置默认**：在依赖安装（`RUN npm ci --omit=dev`）之后、`COPY . .` 之前插一行
  ```dockerfile
  # 安装时区数据（node:20-alpine 默认不含），供 TZ 生效
  RUN apk add --no-cache tzdata
  ```
  `ENV ... TZ=Asia/Shanghai` 放在 ENV 块最后。media_server 已按此落地。
- **compose-on-the-fly（本仓 prod/frontend 服务）**：不能重建镜像时把 `apk add` 塞到服务 `command` 前置：
  ```yaml
  command: sh -c "apk add --no-cache tzdata >/dev/null 2>&1 || true; npm install; npm run dev -- --host 0.0.0.0"
  ```
  `|| true` 兜底 = 镜像已有 tzdata 或 apk 仓库不可达时**不阻断启动**。
**预防**：凡新增 `FROM node:*-alpine` 的 Dockerfile 默认模板里预留 `RUN apk add --no-cache tzdata` 一行（注释 `# 供 TZ 解析`），并在 ENV 块末尾带 `TZ=Asia/Shanghai`，避免上下游复制后丢失。

## 参考

- 源记录: `docs/known-pitfalls/backend/时区与容器.md`
