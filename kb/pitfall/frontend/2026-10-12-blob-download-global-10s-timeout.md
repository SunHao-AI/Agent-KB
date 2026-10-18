---
id: kb-20261012-19b7
title: 大文件下载走全局 10s 超时被 axios abort（`net::ERR_ABORTED` + "系统接口请求超时"）
type: pitfall
domain:
- frontend
tags:
- axios
- timeout
- blob
- download
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-12'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/上传与文件处理.md
---

# 大文件下载走全局 10s 超时被 axios abort（`net::ERR_ABORTED` + "系统接口请求超时"）

## 背景 / 现象

「导出管理」列表中点击「打包下载」`button`（`data-test="pack-download"`），浏览器控制台报两条 `net::ERR_ABORTED`：第一条落在当前行轮询的 `GET /v1/exports?page=1&page_size=20`，第二条落在 `GET /v1/exports/{id}/download`；UI 弹「系统接口请求超时」 toast。但磁盘文件已正常落盘、后端端点 200、axios 拿到的是 `blob` 形式字节流——后端无故障，是**前端 axios 默认 `timeout: 10000`** 与「50MB 量级 blob 下载」不匹配。

## 根因

`src/api/exports.js` 中 `downloadExport(id)` 只传 `responseType: 'blob'`，未覆盖 `timeout`，于是落到 [request.js:21](file:///d:/WorkPlace/Pycharm/flysee-video-setting/frontend/src/utils/request.js#L21) 的全局 `timeout: 10000`。50MB `.zapk` 走 Vite dev proxy（5173 → 8099）+ axios 攒完全部 `blob` 字节后才 resolve，时效远超 10s。axios 在 `onBlobDownload` 期间不会读超时，但在 any 业务层抛出 `ECONNABORTED`/`ERR_CANCELED` 时会从 XHR 发 `abort()`，浏览器侧就落成 `net::ERR_ABORTED`；配合 [request.js:233](file:///d:/WorkPlace/Pycharm/flysee-video-setting/frontend/src/utils/request.js#L233) 的 `message.includes("timeout")` 分支，UI 提示就是「系统接口请求超时」。第二条 abort 命中**当前行轮询**的 `getExportList`（它已覆盖 60s，但短于完整下载时效，被一起 abort），**本质只是"下载长事务把同页短轮询挤掉"的副产品**，不是轮询逻辑 bug。

注意：`createExport` 已自行覆盖 `timeout: 300000`（注释见 [exports.js:12-14](file:///d:/WorkPlace/Pycharm/flysee-video-setting/frontend/src/api/exports.js#L12-L14)），`getExportList` / `getExportDetail` 也覆盖过 60s。**唯独「blob 下载」链路没人写**——这是"超 10s 的请求必须自带 timeout"规律的最后一个盲点。

## 解决方案

[api/exports.js](file:///d:/WorkPlace/Pycharm/flysee-video-setting/frontend/src/api/exports.js) 内：
- `downloadExport(id)` 加 `timeout: 300000`，对齐 `createExport`（同为 50MB 量级、同走 Vite dev proxy）
- `getDiff(id, fromVersion)`（.zdiff blob 下载）加 `timeout: 120000`，与 `getExportList`/`getExportDetail` 的 60s 形成「完整包 300s > diff 包 120s > 列表 60s」的单调档位，**避免"下载 < 列表"的反直觉档位**

配套的 UI 改进可选项（非本次范围）：`handleDownload` 在请求期间把 button 加 `:loading`，避免用户在 axios 还没完全 abort 前重复点击；明确区分"未读完超时"（可重试）与"业务错误"（不可重试）。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/上传与文件处理.md` :: 「大文件下载走全局 10s 超时被 axios abort（`net::ERR_ABORTED` + "系统接口请求超时"）」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例

- 写新 axios 接口（任何 blob/大对象/长事务）时，**默认视为 > 全局 10s**，必须显式覆盖 `timeout`；并把区间对齐——同模块内长短要有单调关系。
- `request.js` 的全局 `timeout` 是「边界默认」，**不是「常规值」**：10s 适合标准 JSON CRUD，凡文件流、批量操作、聚合重计算都应显式声明。建议在 request.js 顶部注释里把这条约定写进 API 契约，避免下一次新增 `download*` 漏掉。
- 与 [`create_export` 端点](file:///d:/WorkPlace/Pycharm/flysee-video-setting/backend/api/v1/exports.py#L40-L56) 同模板：同步端点跑长任务 → 必须 `inline` 走 thread + 前端长 timeout；同时也要把"前端两侧的 timeout 档位"对齐到代码注释里。

## 参考

- 源记录: `docs/known-pitfalls/frontend/上传与文件处理.md`
