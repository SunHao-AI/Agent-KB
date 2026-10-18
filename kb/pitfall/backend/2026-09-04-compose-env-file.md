---
id: kb-20261013-e57b
title: compose 未传 `--env-file` 时只读首个 `-f` 目录的 `.env`，项目根 `.env` 静默失效
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: probable
created: '2026-09-04'
updated: '2026-10-13'
review_by: '2027-01-11'
severity: medium
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/构建与开发环境.md
---

# compose 未传 `--env-file` 时只读首个 `-f` 目录的 `.env`，项目根 `.env` 静默失效

## 背景 / 现象

> 面向：本工作空间全部项目的 `docker/docker-compose*.yml` 启停脚本与手动 `docker compose` 命令（2026-09 端口参数化设计时沉淀）。
2026-09-05
**补充（2026-10-10 复发）**：算法仓 `docker/docker-compose.app.yml` 的 env 来自**双 `--env-file` 链**（`dev.ps1::Get-ComposeArgs`：先 web `.env` 后算法 `.env`，前者提供 `ALGORITHM_UNLOCK_M2M_KEY` 等共享项）。手动 `docker compose -f docker/docker-compose.app.yml up -d --build engine`（漏 `--env-file`）重建容器后，`FLYSEE_WEB_M2M_KEY=${ALGORITHM_UNLOCK_M2M_KEY:-}` 回落空串 → 模型加载 `UnlockPasswordError: FLYSEE_WEB_M2M_KEY 为空`，**任务启动必失败**，而容器照样 healthy（配置缺失不阻启动）。教训两条：① **手动 recreate 多 env-file 项目必须逐字照抄启动脚本的参数**（或直接跑 `scripts\dev.ps1 restart`），别凭记忆拼 `-f`；② **recreate 后必验"空串即致命"的关键 env**——`docker inspect <ctr> --format '{{range .Config.Env}}...' | grep KEY=`，健康检查探不出"配置静默丢失"。

## 根因

`docker compose` 未显式传 `--env-file` 时，自动加载的是"**第一个 `-f` 文件所在目录**"下的 `.env`（compose 文档原文：*it will load the .env file next to the first `-f` file given*）。本项目 compose 在 `docker/` 子目录，`.env` 在项目根，二者不同目录，自动注入必然失效。

## 解决方案

1. 启动脚本显式传 `--env-file`（本工作空间 `scripts/dev.sh` 已落实：`COMPOSE_ARGS=(--env-file "${ENV_FILE}")`）；

2. 变量回落一律用 compose 内 `${VAR:-默认}`，不依赖自动 `.env`（compose `${VAR:-默认}` 是端口默认值的唯一落点）；

3. 手动 `docker compose up`（不经脚本）时若发现一直回落默认，检查 CLI 输出有无 `warning: ... variable not found in environment`。

## 验证

compose 文档原文：*it will load the .env file next to the first `-f` file given*。本项目 compose 在 `docker/` 子目录，`.env` 在项目根，二者不同目录，自动注入必然失效。修复后启动脚本显式传 `--env-file`（`scripts/dev.sh`：`COMPOSE_ARGS=(--env-file "${ENV_FILE}")`）；手动 compose 时检查 CLI 输出有无 `warning: ... variable not found in environment`。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/backend/构建与开发环境.md` 「compose 未传 `--env-file` 时只读首个 `-f` 目录的 `.env`，项目根 `.env` 静默失效」
