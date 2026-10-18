---
id: kb-20261012-040b
title: 并发分片上传被防重复提交误判
type: pitfall
domain:
- frontend
tags:
- upload
- axios
- request-interceptor
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
review_by: '2026-11-01'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/上传与文件处理.md
---

# 并发分片上传被防重复提交误判

## 背景 / 现象

上传模型（尤其目录模型 zip 分片多）时，浏览器反复弹出"数据正在处理，请勿重复提交"，但后端容器日志正常。

## 根因

request.js 的防重复提交拦截器用单一 `sessionObj` 记录最近一次 POST/PUT，1 秒内同 URL 且同 data 即判为重复。分片上传并发（chunked-uploader 并发 3 个）都指向 `/models/upload/chunk`，且 FormData 经 `JSON.stringify` 后均为 `"{}"`，导致并发分片被误判为重复提交而 reject。

## 解决方案

分片上传请求显式禁用防重复提交校验，在 headers 加 `repeatSubmit: false`（拦截器读取 `config.headers.repeatSubmit === false` 即跳过）。凡并发/大文件上传类请求都应如此处理。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/上传与文件处理.md` :: 「并发分片上传被防重复提交误判」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例



源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/上传与文件处理.md` :: 「并发分片上传被防重复提交误判」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/上传与文件处理.md`
