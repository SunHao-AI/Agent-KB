---
id: kb-20261012-4eaa
title: webview 下 getVideoPlaybackQuality().presentedFrames 恒返 0 → 播放器 FPS 浮层恒「0 FPS」（画面明明在动）
type: pitfall
domain:
- frontend
tags:
- webview
- metrics
- player
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-25'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/流媒体播放与预览.md
---

# webview 下 getVideoPlaybackQuality().presentedFrames 恒返 0 → 播放器 FPS 浮层恒「0 FPS」（画面明明在动）

## 背景 / 现象

创建任务页/大窗预览左上角性能浮层恒显示「0 FPS 960x720 丢帧 N」, 但视频画面流畅在动、检测框在更新。曾被误读为"检测拖慢/推流无帧"。

## 根因

FPS 浮层用 `video.getVideoPlaybackQuality().presentedFrames` 每秒差分计算。Trae/Chromium 内嵌 **webview 环境下该 API 对 MSE 直播流恒返回 0**（presentedFrames 不随渲染递增）, 差分恒 0 → FPS 恒 0。`droppedVideoFrames` 仍正常递增（live 低延迟 `enableStashBuffer:false` 的追赶丢帧, 量小属正常）。

## 解决方案

FPS 帧数来源改 **`requestVideoFrameCallback`** 逐帧计数（浏览器每次合成呈现帧回调一次, 与解码器/MSE 实现无关, webview 可用）；环境不支持时回落 `video.currentTime` 增量。丢帧/分辨率保留 `getVideoPlaybackQuality`（这两个字段 webview 正常）。

## 验证

（先证明后端无罪再查前端）: 容器内直接 ffprobe 引擎正在推的 RTMP 输出流 → `r_frame_rate=30/1, avg_frame_rate=30/1`, 3 秒实测 90 帧——**推流管道满帧**。再看 GPU 利用率 43%/显存 4.2G、三段管道进程（拉流 ffmpeg `-re` → worker 推理 → 推流 ffmpeg nvenc）都在跑。问题只剩播放器测量层。

## 适用边界与反例

- **"指标恒 0/恒定值"先怀疑测量 API 在宿主环境失真**, 用独立通路（ffprobe 拉同源流）交叉验证真值, 别顺着 0 去优化被测系统（差点按"FPS 0"去查 GPU/推流, 实际后端满帧）。
- `getVideoPlaybackQuality` 三个字段可靠性不一: `droppedVideoFrames` 普遍可用, `presentedFrames` 在部分 webview/MSE 场景恒 0——测"呈现帧率"首选 `requestVideoFrameCallback`。
- "0 FPS + 丢帧 N"组合有迷惑性: 丢帧非 0 会让人以为有帧在流动, 实际两字段来自同一 API 但一个恒 0 一个正常。

## 参考

- 源记录: `docs/known-pitfalls/frontend/流媒体播放与预览.md`
