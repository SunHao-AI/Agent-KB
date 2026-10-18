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
updated: '2026-10-18'
review_by: '2027-01-16'
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



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/backend/鉴权与会话.md` :: 「pyotp 的 TOTP 参数名是 interval，不是 period」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例





源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/backend/鉴权与会话.md` :: 「pyotp 的 TOTP 参数名是 interval，不是 period」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

