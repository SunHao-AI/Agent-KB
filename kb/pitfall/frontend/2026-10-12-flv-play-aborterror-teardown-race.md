---
id: kb-20261012-a477
title: flv.js play() AbortError「interrupted by a call to pause()」是 teardown 竞态, 不能当错误弹
type: pitfall
domain:
- frontend
tags:
- flv
- play
- race-condition
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-23'
updated: '2026-10-18'
review_by: '2027-01-16'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/流媒体播放与预览.md
---

# flv.js play() AbortError「interrupted by a call to pause()」是 teardown 竞态, 不能当错误弹

## 背景 / 现象

切换任务/关闭 AI 直播弹窗/离开页面时, 控制台报 `[StreamPreview] 播放启动失败: AbortError: The play() request was interrupted by a call to pause()`, 并向用户弹「播放启动失败」toast, 但流本身完全正常（重新进入即可正常播放）。

## 根因

`setup()` 里 `await flvPlayer.play()` 是异步的；在途期间 watch(url/active) 变化或组件卸载触发 `teardown()` → `flvPlayer.pause()/destroy()` + `video.pause()` 打断了未决的 play() promise → 按 AbortError reject。旧代码 catch 里无条件 `console.error + emit('error')`, 把**正常销毁时序**当成播放故障。

## 解决方案

（`components/StreamPreview/index.vue`, 2026-09-23）——「setup 代数」方案：
1. 模块级 `let setupSeq = 0`；`teardown()` 开头 `setupSeq++`（任何接管/销毁都会先 teardown）。
2. `setup()` 在 teardown 旧实例后快照 `const seq = setupSeq`。
3. play() 成功分支加双保险 `if (!flvPlayer || seq !== setupSeq) return`（防止给已被接管的实例置 playing）。
4. catch 里 `if (seq !== setupSeq || !flvPlayer)` → `console.debug` 静默返回, 不弹错；只有**同代实例**的失败才 `console.error + emit('error')`。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/流媒体播放与预览.md` :: 「flv.js play() AbortError「interrupted by a call to pause()」是 teardown 竞态, 不能当错误弹」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例

- **`await x.play()` 的 catch 必须区分"被打断"与"真失败"**：浏览器媒体 play() promise 会被后续 pause()/load()/removeAttribute('src') reject（AbortError/NotSupportedError）, 一切"销毁/重建播放器"的组件都会撞上, 与流质量无关。
- **代数计数器（generation token）比"判实例引用非空"更强**：`!flvPlayer` 只识别"已销毁", 识别不了"销毁后已重建新实例"（此时模块变量又指回非空）, 迟到回执仍会污染新实例状态。teardown++ + 快照比对一次性解决两类。
- 同类第三方库异步 play 竞态可复用此模式（hls.js/dash.js/WebRTC srcObject）, rAF/定时器类回执同理。

## 参考

- 源记录: `docs/known-pitfalls/frontend/流媒体播放与预览.md`
