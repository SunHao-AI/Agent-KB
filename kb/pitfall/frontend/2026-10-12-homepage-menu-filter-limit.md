---
id: kb-20261012-afec
title: 首页本地过滤菜单时，未过滤 vs 已过滤的"上限"不一致
type: pitfall
domain:
- frontend
tags:
- filter
- computed
- homepage
scope: universal
status: accepted
severity: medium
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/表单交互与数据绑定.md
---

# 首页本地过滤菜单时，未过滤 vs 已过滤的"上限"不一致

## 背景 / 现象

首页菜单默认 `slice(0, 10)` 展示前 10 项，但用户输入搜索词后期望能看到全部命中菜单（可能 > 10）。

## 根因

过滤链路若复用 `visibleMenus`（已 `slice(0, 10)`），会导致用户搜索"用户/role/system"时只返回被截断的 10 项里能匹配上的项，馄饨用例（如第 11 条含"系统"的菜单）永远搜不到。

## 解决方案

给搜索单独一条"全量"链路：
- 未搜索：`filteredMenus = visibleMenus`（保留 10 上限的约定）。
- 已搜索：`filteredMenus = walkAll(userStore.menus).filter(match)`（不限制）。

实现方式见 `views/index/index.vue` 中的 `filteredMenus` computed；`walkAll` 抽为独立函数避免多处重复。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/表单交互与数据绑定.md` :: 「首页本地过滤菜单时，未过滤 vs 已过滤的"上限"不一致」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例



源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/表单交互与数据绑定.md` :: 「首页本地过滤菜单时，未过滤 vs 已过滤的"上限"不一致」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/表单交互与数据绑定.md`
