---
id: kb-20261012-9677
title: 健康流被 15s 看门狗误杀：flv.js `MEDIA_INFO` 在 NVENC+node-media-server 组合下根本不触发；`display:none`
  的 video 又被 Chromium「video-only background media was paused to save power」拦截 play()
type: pitfall
domain:
- frontend
tags:
- flv
- media-info
- watchdog
- chromium
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-25'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/流媒体播放与预览.md
---

# 健康流被 15s 看门狗误杀：flv.js `MEDIA_INFO` 在 NVENC+node-media-server 组合下根本不触发；`display:none` 的 video 又被 Chromium「video-only background media was paused to save power」拦截 play()

## 背景 / 现象

引擎推流修复上线后，任务 running、media 有 publisher、事件抓拍正常，但「查看AI直播」仍 15s 报「加载超时：未获取到视频流数据」，console 伴随 `net::ERR_ABORTED http://.../live/out_xxx.flv` 与 `[StreamPreview] 15s 内未收到媒体信息`——而这条流**实际完全健康**。

## 根因

1. flv.js 的 `MEDIA_INFO` 依赖 onMetaData/rtmp 头解析路径，在 NVENC 推流 + node-media-server 分发的组合下**从不触发**（抓包确认 onMetaData 仅 199 字节简版）；把 `MEDIA_INFO` 当作唯一"有数据"判据 → 健康流永远等不到 → 15s 看门狗把健康流判死并 teardown（ERR_ABORTED 又是它的副产物）。
2. 占位期 video `display:none` → Chromium 后台节能策略拦截 `play()`（AbortError），即使数据已进 MSE 并解码就绪（readyState=4）也不推进播放。

## 解决方案

（StreamPreview/index.vue）:
1. 就绪判据改为 **video 元素级事件** `@loadeddata` / `@playing`（任一到达即证明对端有 publisher 在出数据）：解除看门狗 + 进入播放态；`MEDIA_INFO` 降级为补充信号。死会话（无 publisher）`loadeddata` 同样永不到来，看门狗语义不变。
2. `reveal()` 在 `nextTick`（元素已可见）后对 `el.paused` 的 video **补偿性 `el.play()`**，化解 `display:none` 期被后台节能拦截的首次 play()；该 AbortError 归入良性时序 debug 降级。
3. E2E 验证：video 960x720、`paused=false`、currentTime 持续 17.2s、浮层 30 FPS 960x720——AI直播出画。

## 验证

1. 宿主 `curl` HTTP-FLV 6s → 3.1MB（≈4Mbps），FLV 魔数 `46 4C 46 01` 正确，Python 手拆 tag 链合法（SCRIPT+VIDEO H.264, SPS 960x720, GOP=33）；`ffprobe` 同文件解析正常 → **数据面无罪**。
2. media 日志每次 `prePlay/postPlay/donePlay(15s)` 成对出现 → 浏览器请求**到达了** media 且看门狗到点主动 abort（`ERR_ABORTED` 是 teardown 的正常副产物）。
3. 在预览浏览器页面内直接原生 `fetch` 同一 URL：6s 收到 3,032,613 字节 → **浏览器数据通路无罪**（此前怀疑 Electron 代理缓冲不成立）。
4. 页面内注入独立 flv.js 实例监听全事件：STATISTICS 显示持续收数、video `readyState=4`、`videoWidth=960`——**解码渲染全部正常**，唯独 `MEDIA_INFO` 事件全程不发。
5. `play()` reject 的 AbortError 文案给出最后一块拼图：`The play() request was interrupted because video-only background media was paused to save power`——组件用 `v-show`（`display:none`）藏 video，Chromium 对不可见的纯视频元素直接拒绝 play() 并暂停加载。

## 适用边界与反例

- **播放"就绪"的权威判据是媒体元素状态（readyState/loadeddata/playing），不是解析库的派生事件**：flv.js `MEDIA_INFO` 触发条件受服务端 onMetaData 内容影响（hls.js 同理 `levels` 事件）；库事件不发≠没数据，`STATISTICS_INFO`/`video.readyState` 才是地面真相。
- **`display:none` 的 video 会被 Chromium 节能策略拦截 play()/降载**（`paused to save power`），预加载/占位期需要播放时：要么保持元素可见（`opacity:0`/移出视口），要么显示后补偿 play()。
- **自己加的看门狗也会咬人**：超时判失败的兜底必须建立在"无数据"的可靠判据上；健康流被误杀时，症状与目标故障（真无流）一模一样，只能靠分层探测（curl→页面 fetch→注入实例事件）区分。
- **AbortError 的 detail message 是关键鉴别信息**：`interrupted by pause()` / `removed from the document` / `paused to save power` 是三种完全不同的时序，只记 `err.name` 会丢掉最值钱的那半。

## 参考

- 源记录: `docs/known-pitfalls/frontend/流媒体播放与预览.md`
