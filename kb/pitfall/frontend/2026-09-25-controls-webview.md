---
id: kb-20261013-a8c3
title: 原生 controls 无法按轨道隐藏单个按钮 → 自绘控制条替代（音轨探测 + webview 全屏降级）
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
severity: low
confidence: probable
created: '2026-09-25'
updated: '2026-10-13'
review_by: '2027-01-11'
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/流式播放与预览.md
---

# 原生 controls 无法按轨道隐藏单个按钮 → 自绘控制条替代（音轨探测 + webview 全屏降级）

## 背景 / 现象

直播预览用原生 `controls`，而推流命令是 `rawvideo`（纯视频、无音轨）→ 浏览器把音量按钮渲染成**禁用灰态**常驻，用户反复点击以为故障。原生 API 只能整体 `controlslist` 屏蔽（同样只是禁用不隐藏），无法"无音轨时不显示音量项"。

## 根因

- **音轨探测双路**：flv.js `MEDIA_INFO`（`audioCodec`/`audioDataRate`）+ 秒级节拍里读元素 `videoTracks`/`audioTracks`，任一路有音即 `hasAudioTrack=true` 并渲染音量项；`teardown()` 复位 false，防跨会话残留。

- **初始静音**：`isMuted` 初值 true，满足浏览器自动播放策略（带声自动播放会被拒）。

- **全屏降级**：内置浏览器（Electron webview）里 `requestFullscreen()` 的 promise **永远 pending**（既不 resolve 也不 reject，`.catch` 兜底是死的）→ 600ms 超时探测后降级 CSS「网页全屏」（`fixed inset-0` 盖过 el-dialog，ESC/再点退出）；原生态生效时摘降级态防叠加。

- **自动隐藏**：播放中 3s 无鼠标活动隐藏、`mousemove` 唤醒、暂停时常显（`controlsHidden` + `wakeControls` 单一 timer，`teardown` 必 `clearControlsTimer`）。

- **暂停态不直接信 `el.paused`**：happy-dom/后台节能场景失真，组件内 `paused` 乐观切换 + 秒级统计节拍与元素对账。

- **宿主不实现的 API 表现为"永不 settle"而非 reject**：任何依赖浏览器能力做 UI 分支的地方，必须用超时探测而非 `catch`；验收要在目标宿主（内置 webview / 真 Chrome）**真点一次**。

- **原生控件的可用性由媒体轨道决定**：`controlslist` 与轨道缺失都只造成"禁用"而非"隐藏"，需要真正隐藏只能自绘。

- 真流行为（音轨探测准确率、自动播放策略、FLV 长会话下的暂停/恢复）**单测覆盖不到**，须在真实直播弹窗人工复核。

## 解决方案

去掉 `controls`，组件自绘控制条（播放/暂停、已播时长、音量+静音、全屏），按探测到的轨道条件渲染：

## 验证

内置浏览器（Electron webview）实测：`requestFullscreen()` 的 promise **永远 pending**（既不 resolve 也不 reject，`.catch` 兜底是死的）→ 600ms 超时探测后降级 CSS「网页全屏」（`fixed inset-0` 盖过 el-dialog，ESC/再点退出）；原生态生效时摘降级态防叠加。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/流式播放与预览.md` 「原生 controls 无法按轨道隐藏单个按钮 → 自绘控制条替代（音轨探测 + webview 全屏降级）」
