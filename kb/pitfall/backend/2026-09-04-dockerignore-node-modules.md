---
id: kb-20261013-ff29
title: '`.dockerignore` 裸写 `node_modules` 不递归，前端依赖被整个打进后端镜像'
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
severity: medium
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/构建与开发环境.md
---

# `.dockerignore` 裸写 `node_modules` 不递归，前端依赖被整个打进后端镜像

## 背景 / 现象

> 面向：`flysee_video_web` 后端镜像（根 `Dockerfile`，build context 为仓库根目录）。

## 根因

根 `.dockerignore` 里写的是裸 `node_modules`、`frontend/dist`、`logs`。Docker 的忽略模式**按 build context 根相对路径匹配**，裸 `node_modules` 等价 `./node_modules`，**匹配不到子目录里的 `frontend/node_modules`（280.7 MB）**；`data/model_cache`（63.4 MB 模型缓存）与 `.venv`（134.5 MB，已被根级规则命中）同理，只要目录不在 context 根一级就会漏网。这些目录又被根 `Dockerfile` 的 `COPY . .` 全量纳入，于是 context 与镜像一起膨胀。

## 解决方案

把根 `.dockerignore` 改成递归模式并排除整体前端目录：

```dockerignore

# 前端源码与依赖：backend 镜像不需要

# （frontend 镜像以 frontend/ 为独立 build context，配 frontend/.dockerignore，不受本文件影响）

frontend

# 兜底：Docker 忽略模式按根相对路径匹配，裸 `node_modules` 匹配不到 frontend/node_modules

**/node_modules

# 运行时产物：容器内由 os.makedirs(exist_ok=True) 现场创建，不应固化进镜像

data

logs

**/__pycache__

.venv

.pytest_cache

.mypy_cache

.ruff_cache

```

效果：**build context 363+ MB → 11.46 kB**，`transferring context` 从 550+ s 降到 8.2 s。

## 验证

- 排除项确实是运行时可再生的：`data/model_cache`、`data/license`、`logs` 全部由代码 `os.makedirs(..., exist_ok=True)` 现场创建；`backend/` 内无任何 `frontend`/`dist` 引用（`Grep` 核对）；`pyproject.toml` 的 `[tool.setuptools.packages.find] include = ["backend*"]` 说明 editable 安装只需要 `backend/`。

- 构建后 `docker run --rm <image> python -c "import backend.main"` 通过，`ls /app` 确认 `backend`/`tests`/`scripts` 仍在。

## 适用边界

- 排除依赖目录一律写 `**/node_modules`、`**/__pycache__`，别指望裸名递归；

- 瘦身 `.dockerignore` 时**不要顺手排除 `tests`/`docs`/`scripts`**——它们合计数 MB，收益可忽略，却会让"容器内跑 pytest / 读 docs"这类用法静默失效；只排体积大头 + 运行时可再生产物；

- 判断 context 该排什么，先量一遍：`Get-ChildItem -Directory | 递归 Measure-Object Length -Sum`，按 MB 倒序取前几名即可命中真凶；

- 双 stage 镜像中，`COPY . .`（运行阶段全量拷贝）会把 context 里所有非忽略文件带进最终镜像，瘦身收益同时体现在 context 与镜像两层。

## 参考

- 源记录: `docs/known-pitfalls/backend/构建与开发环境.md` 「`.dockerignore` 裸写 `node_modules` 不递归，前端依赖被整个打进后端镜像」
