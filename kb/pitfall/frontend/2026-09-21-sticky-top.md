---
id: kb-20261013-cca6
title: 右栏 sticky 的 top 写死导航高度，与左栏首卡顶部错位
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-21'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: low
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/表格布局与对齐.md
---

# 右栏 sticky 的 top 写死导航高度，与左栏首卡顶部错位

## 背景 / 现象

创建分析任务页右栏（实时预览卡）比左栏「视频源」卡低 42px，视觉上两栏顶部不对齐。

## 根因

`.create-task-layout__rail { position: sticky; top: 104px }` 按"navbar 50 + tags-view 34 + 呼吸"算，但**滚动容器是 `.app-main`**（`.fixed-header + .app-main` 已 `margin-top: 84px` + `height: calc(100vh - 84px)` + `overflow-y: auto`）。sticky 的 `top` 相对**滚动容器可视顶**，导航高度已在容器外侧扣掉，再写 104px 等于重复扣一次。

## 解决方案

`top: 16px`（只留呼吸值）。实测两栏 `getBoundingClientRect().top` 差值为 0。

## 验证

改 `top: 16px`（只留呼吸值）后，实测两栏 `getBoundingClientRect().top` 差值为 0。

## 适用边界

设 sticky/`scroll-padding` 的偏移前先确认**最近的滚动祖先**是谁——吸顶栏在滚动容器外侧时，其高度绝不能计进 `top`。

## 参考

- 源记录: `docs/known-pitfalls/frontend/表格布局与对齐.md` 「右栏 sticky 的 top 写死导航高度，与左栏首卡顶部错位」
