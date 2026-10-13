---
id: kb-20261012-e55b
title: 容器进程未重启导致运行旧 Schema（bind mount 热重载失效）
type: pitfall
domain:
- backend
tags:
- bind-mount
- hot-reload
- openapi-probe
- stale-process
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-01'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/测试与开发环境.md
---

# 容器进程未重启导致运行旧 Schema（bind mount 热重载失效）

## 背景 / 现象

> 面向：`flysee-video-setting` 后端（FastAPI）。

**现象**：前端上传模型时 `POST /v1/models/upload/init` 返回 `422`，校验错误为 `model_type: Input should be a valid string`，但源码中 `InitUploadRequest.model_type` 已是 `list[str]`。

## 根因

**根因**：后端容器 bind mount 源码（`backend/`），但运行进程仍是旧代码。磁盘上 `model_file.py` 在容器启动后被修改（`model_type` 从 `str="yolo"` 改为 `list[str]=["detect"]`），而 `uvicorn --reload` 未捕获该改动，进程仍用旧 `str` 类型校验，前端发送数组 `['detect']` 即触发 422。

## 解决方案

**解决**：改动后端 Schema/代码后，若 `--reload` 未生效，需主动重启容器加载新代码：`docker restart flysee-video-setting-backend`。排查时可用 `curl` 请求 `/openapi.json` 对比运行进程实际 Schema 与源码是否一致，快速定位"进程旧代码"问题。

## 验证

原文实录: `POST /v1/models/upload/init` 返 422 `model_type: Input should be a valid string` 而源码已是 `list[str]`; 排查探针为 curl `/openapi.json` 对比运行进程实际 Schema 与源码是否一致。

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->



## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
