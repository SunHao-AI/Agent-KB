---
id: kb-20261013-3a62
title: '直播流首帧链路的隐藏大头: ffprobe/ffmpeg 默认 analyzeduration=5s 串行白等 ~10s'
type: pitfall
domain:
- algorithm
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-25'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: medium
source:
  project: flysee_video_algorithm
  ref: docs/known-pitfalls/engine/TRT引擎校验与冷启动预热.md
---

# 直播流首帧链路的隐藏大头: ffprobe/ffmpeg 默认 analyzeduration=5s 串行白等 ~10s

## 背景 / 现象

**注意**：fps 探测不能整体异步化——`_spawn_push_pipe` 需要真实 fps 作输出帧率,
ack（running）以首帧推流为准, 故 ffprobe 窗口必然在关键路径上, 只能压缩不能摘除。
GPU 抢占会剧烈放大各阶段实测值（与运行中任务共享 GPU 时 first predict 实测 8.1s,
独占时仅 1.2s）, 性能归因实验必须独占 GPU。

## 根因

ffprobe/ffmpeg 对直播流默认 `analyzeduration=5s`（攒够 5 秒数据或 5MB

probesize 才返回/开始解码）; 且 `Detector.start()` 先串行跑完 ffprobe 拿 fps 才拉起

读流 ffmpeg, 两段 5s 串行叠加。

## 解决方案

1. `get_video_info` 的 ffprobe 加 `-analyzeduration 3000000 -probesize 3000000`

   （下限须覆盖源关键帧间隔, sim_push g=30@25fps=1.2s; 拿不到 fps 走既有重试兜底）;

2. `create_read_ffmpeg` 直播分支加 `-analyzeduration 1000000 -probesize 500000`

   （尽快出帧; 首帧解码仍需等一个关键帧, 由源 GOP 决定, 无法绕过）;

3. `start()` 里 `read_pipe = create_read_ffmpeg(...)` **先于** `get_video_info` 执行,

   两个 ffmpeg 并行探测同一路流（读管道 `bufsize=10^8` 在等待期缓冲帧）;

   ffprobe 失败时 read_pipe 由 `detect()` finally → `stop()` → `close_read_ffmpeg`

   兜底清理, 无泄漏。

## 验证

GPU 抢占会剧烈放大各阶段实测值（与运行中任务共享 GPU 时 first predict 实测 8.1s，独占时仅 1.2s），性能归因实验必须独占 GPU。

## 适用边界

本条来自 flysee_video_algorithm 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/engine/TRT引擎校验与冷启动预热.md` 「直播流首帧链路的隐藏大头: ffprobe/ffmpeg 默认 analyzeduration=5s 串行白等 ~10s」
