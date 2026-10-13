---
id: kb-20261012-3aae
title: 安装错误码语义与文档不一致
type: pitfall
domain:
- frontend
tags:
- error-code
- spec
- cross-platform-contract
scope: universal
status: accepted
severity: high
confidence: probable
created: '2026-09-12'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/应用包闭环形态.md
---

# 安装错误码语义与文档不一致

## 背景 / 现象

spec 初稿写「`E_INSTALL_001`=口令错、`E_INSTALL_002`=包无效」；但 `backend/api/v1/algorithm_suites.py:50-95` 实际代码：
- `E_INSTALL_001` = 系统尚未初始化（instance 未建）
- `E_INSTALL_002` = 密码错误（口令不匹配）
- `E_INSTALL_003` = 其他（含包无效、SHA256 校验失败，detail 内嵌 exc）
- `E_UPDATE_001` = 增量包不匹配（回退整包）

spec 错了 → 按 spec 实施前端错误分流必错（口令界面会按 001 分支走「未初始化」，包无效按 002 分支走「口令重新输入」，前后矛盾）。

## 根因

spec 初稿基于口头描述而非代码事实；编写者未读 `algorithm_suites.py` 实际抛错位置就写了错误码分配。

## 解决方案

1. 写 spec 前先把 backend 错误映射读一遍（`Grep "E_INSTALL_" backend/api/v1/algorithm_suites.py` + `Grep "raise " backend/services/suite_service.py`），把实际码→语义表写进 spec 顶部「对 spec 的事实修正」；
2. 本轮实施遵循**代码实际**，前端 `installErrorMessage(err)` 按码前缀分流：001→「初始化」、002→「口令」、003→「重新获取」、E_UPDATE_001→「整包」、无码→透传 detail；
3. pytest 关键断言（`tests/test_suite_install.py`）：成功用例的 `inst.error if hasattr(data, 'error')` 文本 = `E_INSTALL_xxx: 人话` 前缀（含 exc 字符串），前端再按前缀分流；
4. **错误码前缀（`E_INSTALL_00x`/`E_UPDATE_00x`）是不可改契约**，因为 web 前端 + web cron worker 都按前缀分流 SDK 内部 vs 用户可见的 retry 策略。改码必须同步改前端 + 改 spec + 改 worker。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

错误码是 SDK 跨端契约（后端抛 → 前端分流 → cron worker retry）。映射表必须有"代码引用行号"作 spec 锚点，且**前缀（`E_INSTALL_001`）一旦上线不可改**，语义改了只改 detail 字符串。前端错误文案分流必须 100% 按前缀，不要再按 message 子串猜。

## 参考

- 源记录: `docs/known-pitfalls/frontend/应用包闭环形态.md`
