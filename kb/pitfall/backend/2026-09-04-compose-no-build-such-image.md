---
id: kb-20261013-fd0d
title: compose 服务改名后镜像名连锁变化，`--no-build` 启动报 No such image
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-04'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: low
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/构建与开发环境.md
---

# compose 服务改名后镜像名连锁变化，`--no-build` 启动报 No such image

## 背景 / 现象

> 面向：`flysee_video_web`（compose 项目名 `flysee-video-web`，`web-backend` 服务更名为 `backend`）。

## 根因

compose 对 build 型服务的默认镜像名是 `<project>-<service>`。服务名从 `web-backend` 改成 `backend`，期望镜像名随之从 `flysee-video-web-web-backend` 变为 `flysee-video-web-backend`，旧镜像不会自动改名。旧名里的双 `web` 前缀正是本次更名要消除的命名混乱来源。

## 解决方案

服务改名后重新 `docker compose build backend` 产出新名镜像（context 瘦身后仅 44s），再 `docker rmi` 旧名镜像；同时用 `up -d --remove-orphans` 清掉旧服务名遗留的孤儿容器。前端 `BACKEND_PROXY_TARGET` 这类**按服务名寻址**的环境变量必须同步改（Docker 网络内 DNS 按服务名解析），本例 `http://web-backend:17998` → `http://backend:17998`。

## 验证

服务改名后重新 `docker compose build backend` 产出新名镜像（context 瘦身后仅 44s），再 `docker rmi` 旧名镜像；同时用 `up -d --remove-orphans` 清掉旧服务名遗留的孤儿容器。

## 适用边界

改 compose 服务名前先 `Grep` 全仓引用（compose 互引 `depends_on`/`links`、环境变量里的服务名主机、脚本里的 `logs -f <service>`、`DEV_SERVICES` 列表）；改名验证用 `docker compose config --services` 看合并结果，不要只看文件。

## 参考

- 源记录: `docs/known-pitfalls/backend/构建与开发环境.md` 「compose 服务改名后镜像名连锁变化，`--no-build` 启动报 No such image」
