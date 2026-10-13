---
id: kb-20261012-d47f
title: pyotp 的 TOTP 参数名是 interval，不是 period
type: pitfall
domain:
- backend
tags:
- pyotp
- totp
- api
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/鉴权与会话.md
---

# pyotp 的 TOTP 参数名是 interval，不是 period

## 背景 / 现象

> 面向：`flysee-video-setting` 后端（FastAPI）。

**现象**：调用 `pyotp.TOTP(secret, digits=6, period=30)` 直接 `TypeError: TOTP.__init__() got an unexpected keyword argument 'period'`。

## 根因

**根因**：pyotp 上游把周期参数命名为 `interval`（old 版本叫 `period`），与 RFC 6238 文档惯例 `period` 不一致，文档有歧义。

## 解决方案

**解决**：凡是用 pyotp 的代码统一 `interval=30`；保留 `digits=6` 不变。建议服务端常量与客户端常量名一致（如 `TOTP_PERIOD` 仅作业务语义名，pyotp 调用处显式 `interval=SEC.TOTP_PERIOD`）。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例



## 参考

- 源记录: `docs/known-pitfalls/backend/鉴权与会话.md`
