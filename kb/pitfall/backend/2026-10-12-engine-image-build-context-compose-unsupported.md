---
id: kb-20261012-d477
title: flysee engine 镜像不能用 `docker compose build`（BuildKit 命名上下文）：必须走 scripts\build-engine.ps1
type: pitfall
domain:
- backend
tags:
- buildkit
- named-build-context
- docker-compose
- env-file
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-23'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/性能与容错优化.md
---

# flysee engine 镜像不能用 `docker compose build`（BuildKit 命名上下文）：必须走 scripts\build-engine.ps1

## 背景 / 现象

**现象**：改完 `app/` 代码想用 `docker compose -f docker/docker-compose.app.yml build engine` 固化进镜像, 构建在 `COPY --from=cudnn_prefetch / /tmp/prefetch/` 层失败, BuildKit 报去 registry 解析 `cudnn_prefetch` 镜像 403/404。

## 根因

**根因**：`Dockerfile.trt86` 的 `COPY --from=cudnn_prefetch` 依赖 BuildKit **命名构建上下文**（named build context）, 只有 `docker build --build-context cudnn_prefetch=<wheel目录>` 能注入；`docker compose build` 无传 `--build-context` 的入口, BuildKit 退化为把 `cudnn_prefetch` 当远程镜像拉 → 必失败。

## 解决方案

**正解**：`powershell -ExecutionPolicy Bypass -File scripts\build-engine.ps1`（已封装: ① `.wheelhouse/cudnn_prefetch/` 缺 wheel 先 `pip download`(带 `--platform manylinux1_x86_64 --python-version 310` 交叉下载参数) ② `docker build -f Dockerfile.trt86 --build-context cudnn_prefetch=<dir> -t flysee-video-algorithm-app:trt86 .` ③ 自动 `compose up -d engine`）。tag 默认 `trt86` 对齐 compose `image: flysee-video-algorithm-app:${ALGO_IMAGE_TAG:-trt86}`, 构建完 up 即用新镜像。

## 验证

原文实录: compose build 在 `COPY --from=cudnn_prefetch` 层失败、BuildKit 去 registry 解析 403/404; 正解 build-engine.ps1 实测构建完 up 即用新镜像, 判生效以容器内 `inspect.getsource` 探针为准。

## 适用边界与反例

**要点**：
- **判定某仓 engine 镜像怎么 build, 先看 Dockerfile 有没有 `COPY --from=<非数字/非阶段名>`**——那是命名上下文, compose build 一律不支持, 只认 `docker build --build-context`。
- 镜像内代码非 bind mount 时（本例 `COPY . .`）: `docker restart` 跑旧码, `docker cp`+restart 仅临时, **固化只有 rebuild**。判生效以容器内 `python -c "import inspect,app.engine.yolov.inference as m; print('copy()' in inspect.getsource(m))"` 为准, 别看宿主文件。
- `.dockerignore` 未排 `app/`/`run.py` → rebuild 会把工作区最新代码整体打进去, 是固化的前提; 但也意味着构建前确认工作区是期望状态。
- **`.wheelhouse/`（cudnn 预取 wheel ~696MB）必须在 `.dockerignore` 里排除**：它经 `--build-context cudnn_prefetch` 单独注入, 不排除会被当主构建上下文整体传 BuildKit（实测每次 build 白传 696MB / +200s）。
- **`compose up` 漏 `--env-file` 会让 `${VAR:-}` 静默插空**：engine 编排变量（`ALGORITHM_UNLOCK_M2M_KEY` 等共享配置）单一事实源在 web `.env`, 算法仓 `.env` 没有。`docker compose ... up -d engine` 不带 `--env-file web\.env --env-file .env` 时插值取 `:-` 空默认 → `FLYSEE_WEB_M2M_KEY` 空 → 模型加载报 `UnlockPasswordError: 凭据未配置`（容器仍 healthy, 只任务失败）。`scripts\build-engine.ps1` 已在 up 处固定带双 env-file; 手工 up 勿省。

## 参考

- 源记录: `docs/known-pitfalls/backend/性能与容错优化.md`
