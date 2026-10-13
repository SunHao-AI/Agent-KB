---
id: kb-20261012-d031
title: 分片上传遇后端热重载报 ERR_CONNECTION_RESET
type: pitfall
domain:
- frontend
tags:
- upload
- chunked-upload
- vite
- uvicorn
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-01'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/上传与文件处理.md
---

# 分片上传遇后端热重载报 ERR_CONNECTION_RESET

## 背景 / 现象

模型上传过程中浏览器控制台报 `net::ERR_CONNECTION_RESET http://localhost:5173/v1/models/upload/chunk`，但后端容器日志无 Traceback、到达后端的 chunk 均返回 200。

## 根因

开发模式下后端以 `uvicorn --reload` + bind mount 运行，任何源文件改动都会触发进程重启（Shutting down → startup complete，约 2~3s 停机窗口）。若某个 chunk POST 恰好落在该窗口内，TCP 连接被重置即报 ERR_CONNECTION_RESET。这是 dev 热重载的正常行为，非分片逻辑 bug；Vite(5173) 代理 `/v1`→后端(8099)，故错误 URL 显示为前端端口。

## 解决方案

`ChunkedUploader._uploadChunkWithRetry` 按错误类型区分重试预算——瞬时网络错误（无响应 / ECONNRESET / ERR_NETWORK / ECONNABORTED）用更大的 `maxTransientRetries` 与更长初始退避覆盖服务重启窗口；有 HTTP 响应的业务错误仍走普通重试。前提是分片写入幂等（同 upload_id+index 重复写会覆盖），可安全重发。排查此类"偶发断连"时先看是否由源码改动触发的 reload 引起。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->

## 参考

- 源记录: `docs/known-pitfalls/frontend/上传与文件处理.md`
