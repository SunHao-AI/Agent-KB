---
id: kb-20261012-23fc
title: Docker 构建时直连 PyPI 下载依赖长时间停滞
type: pitfall
domain:
- backend
tags:
- docker-build
- pypi-mirror
- uv
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-01'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/测试与开发环境.md
---

# Docker 构建时直连 PyPI 下载依赖长时间停滞

## 背景 / 现象

> 面向：`flysee-video-setting` 后端（FastAPI）。

**现象**：`dev.ps1 start` 构建镜像时，app 阶段 `RUN pip install uv && uv sync --frozen` 卡在 `Downloading ... (20.9 MB)` 超过 8 分钟无进展（frontend 的 npm install 正常）。

## 根因

**根因**：Dockerfile builder 阶段 pip/uv 默认直连 `pypi.org`，国内网络下不稳定或极慢；Docker Hub 拉镜像走了代理但容器内构建进程不一定复用宿主机代理。

## 解决方案

**解决**：在 [Dockerfile](../../../Dockerfile) builder 阶段显式加国内镜像源环境变量（pip 用 `PIP_INDEX_URL`，uv 用 `UV_DEFAULT_INDEX`），例如清华源 `https://pypi.tuna.tsinghua.edu.cn/simple`；加后 uv wheel 以 ~9 MB/s 下载，全部依赖约 1 分钟装完。

## 验证

原文实测: 卡 `Downloading ... (20.9 MB)` 超 8 分钟无进展; builder 阶段加 `PIP_INDEX_URL`/`UV_DEFAULT_INDEX` 清华源后 uv wheel 以 ~9 MB/s 下载, 全部依赖约 1 分钟装完。

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->



## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
