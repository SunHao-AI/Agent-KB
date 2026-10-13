---
id: kb-20261012-d23b
title: 'AbortError「media was removed from the document」: Teleport(append-to-body)
  移挂 video 打断在途 play(), 代数判不住须按错误名识别; teardown 主动拆除触发的 flv ERROR 须先 off'
type: pitfall
domain:
- frontend
tags:
- teleport
- flv
- teardown
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-25'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/流媒体播放与预览.md
---

# AbortError「media was removed from the document」: Teleport(append-to-body) 移挂 video 打断在途 play(), 代数判不住须按错误名识别; teardown 主动拆除触发的 flv ERROR 须先 off

## 背景 / 现象

打开/关闭「放大」大窗瞬间控制台报 `[StreamPreview] 播放启动失败: AbortError: The play() request was interrupted because the media was removed from the document` + 伴随 flv.js 内部 `[IOController]/[TransmuxingController] NetworkError/IOException: Failed to fetch` 与浏览器自记的 `net::ERR_ABORTED ...flv?sign=...`。播放本身不受影响。

## 根因

（与「interrupted by pause()」同族但两条新路径）:
1. `el-dialog append-to-body` 是 Teleport——`bigPreviewVisible` 翻转把 `<video>` 节点**移挂到 body** 的瞬间, 在途 `play()` 被浏览器 reject(AbortError)。此刻 `teardown()` 还没跑, `flvPlayer` 非空且 setupSeq 代数匹配 → 旧的代数保护判不住, 落进 console.error。
2. teardown 主动 `unload()/destroy()` 会打断在途 loader, flv.js 异步派发 ERROR 事件 → 又一条"自己拆自己"的假故障。

## 解决方案

（三道防线）:
1. catch 条件补 `err?.name === 'AbortError'` → 良性打断统一降级 debug（真故障 NotSupportedError/网络错误不带 AbortError 名, 照常上报）。
2. ERROR 监听器具名化存 `currentErrorHandler`, `teardown()` 里 **pause/unload 之前先 `flvPlayer.off(ERROR, handler)`**。
3. handler 内再加代数二次防线（events.js 派发队列可能在 off 前已拷贝回调, 迟到执行时代数已不符 → debug 静默）。

回归单测补 3 例（mock 加 `off()` 与 `_emitError` 钩子）: teardown 后迟到 ERROR 静默 / off 前拷贝的回调晚到走二次防线 / 未经 teardown 的移挂 AbortError 静默。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

- **Teleport 移挂 DOM 节点同样打断在途 play()**: "元素移出文档"与"调用 pause()"都会 AbortError, 但前者发生时组件视角的"销毁"尚未开始, 所有基于 teardown 时刻的代数/标志保护都有窗口期漏洞, **按 `err.name === 'AbortError'` 识别是最终兜底**。
- **主动销毁第三方播放器前先摘它的事件监听**: unload/destroy 触发的事件是"自己拆自己"的信号, 不是故障; 监听器必须在 teardown 首段 off 掉, 且 handler 内部保留幂等的代数判断防迟到派发。
- `net::ERR_ABORTED` 是浏览器对 abort fetch 的自记日志, **JS 无法抑制**, 与页面刷新打断在途请求同款, 属残余噪声不必再修。

## 参考

- 源记录: `docs/known-pitfalls/frontend/流媒体播放与预览.md`
