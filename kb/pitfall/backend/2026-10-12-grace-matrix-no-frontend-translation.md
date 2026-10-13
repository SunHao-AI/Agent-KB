---
id: kb-20261012-9272
title: 前端禁止把方法级封锁翻译成业务动作清单（宽限矩阵单口径）
type: pitfall
domain:
- backend
tags:
- grace-policy
- frontend
- single-source
scope: universal
status: accepted
severity: medium
confidence: verified
created: '2026-10-12'
updated: '2026-10-13'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/密钥与授权轮换.md
---

# 前端禁止把方法级封锁翻译成业务动作清单（宽限矩阵单口径）

## 背景 / 现象

> 面向：授权过期宽限期内"哪些操作还能用"的前端展示（web 仓 grace_policy / 矩阵 UI，2026-10-11 授权管理 UX 优化 T6/T8）。

**现象**：后端中间件的宽限期封锁口径是**方法级**（禁 POST/PUT/PATCH/DELETE 写方法，`ALWAYS_ALLOWED_PATHS` 精确白名单例外）。前端做"宽限期可用性矩阵"若把口径**翻译成业务动作名清单**（"不能续费/不能上传模型/…"），等于维护第二份口径：后端加一个写端点或改白名单，矩阵立即失真，且失真方向是误导客户"还能做/不能做"。

## 根因

后端封锁按 HTTP 方法在中间件统一拦截, 生效范围只随路由注册与白名单变化; 前端把它翻译成业务动作名清单等于固化一个翻译时刻的快照, 新增写端点或调整 `ALWAYS_ALLOWED_PATHS` 不会触发前端任何告警, 矩阵遂静默失真为第二份口径.

## 解决方案

**方案**：前端矩阵数据**直接消费后端下发的 `grace_policy`**（后端内部 `list(ALWAYS_ALLOWED_PATHS)` 直接导出，无复制清单），描述文案用方法级表述（"过期宽限期内禁止一切写操作，例外路径以清单为准"），不出现业务动作名枚举。

## 验证

原文「要点」回归锁：断言 grace_policy 内容与 `ALWAYS_ALLOWED_PATHS` 集合相等 + 矩阵文案 banned 断言（不含业务动作名词表）。

## 适用边界与反例

**要点**：
- 回归锁：断言 grace_policy 内容与 `ALWAYS_ALLOWED_PATHS` 集合相等 + 矩阵文案 banned 断言（不含业务动作名词表）。
- 同族教训：任何"后端规则 → 前端展示"的翻译层都要问一句"规则变了这里会静默过期吗"；会，就改成下发而非翻译。

## 参考

- 源记录: `docs/known-pitfalls/backend/密钥与授权轮换.md`
