---
id: kb-20261012-f552
title: 任务 output 存浏览器视角地址直接派发进容器：引擎 ffmpeg 推到自身 loopback, 任务假 running 永无流
type: pitfall
domain:
- backend
tags:
- container-namespace
- url-rewrite
- dispatch-boundary
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-23'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/测试与开发环境.md
---

# 任务 output 存浏览器视角地址直接派发进容器：引擎 ffmpeg 推到自身 loopback, 任务假 running 永无流

## 背景 / 现象

> 面向：跨「浏览器 / web 后端 / 容器内引擎」三方的流地址传递（本例 `flysee_video_web` 派发链 → `flysee_video_algorithm` engine，2026-09-23）。

**现象**：创建任务后前端预览永远「视频流接入中…」；引擎日志反复 `Error opening output rtmp://127.0.0.1:1937/...: Connection refused`；但 DB 里任务照转（pending→被派发→ffmpeg 重试），用户侧只看到"无流"。

## 根因

**根因**：一个地址三种视角——前端「输出流地址」预填 `rtmp_base`（**宿主/浏览器视角** `127.0.0.1:1937`，给用户复制/预览用，本身没错），`_to_engine_payload` 把 `output→rtmp` **原样**透传给容器内引擎；engine 容器里 `127.0.0.1` = 引擎自身，media 不在那里 → 必然 refused。宿主机裸跑时代该地址恰好能用，容器化后语义悄悄变了。

## 解决方案

**方案**（`task_service._to_engine_payload`，与仓内 `media_http_container_url` 同款分派惯例）：
1. config 新增 `media_rtmp_container_url` property：`in_container()` → `rtmp://media:<CONTAINERPORT>`，否则回落宿主 base；
2. 派发出口在 `sign_stream_url` **之后**做前缀重写：`val.startswith(media_rtmp_base_url)` → 换成 container base。顺序关键：media 签名只覆盖 stream path（不含 host），签名后换 host 不破坏验签；前缀匹配保证第三方 rtmp 地址原样不动；
3. 宿主裸跑时两 base 相同 → 零行为变化。

## 验证

原文「冒烟判据链(逐层证明)」: `_to_engine_payload` 容器内输出 `rtmp://media:1937/...?sign=` → 引擎日志 `Output #0, flv, to 'rtmp://media:1937/...'` 且 0 refused → `[START TIMING] to_running=` → media FLV 带 sign 拉流 200 + 首块字节。

## 适用边界与反例

**要点**：
- **容器化改造要枚举所有"存下来的 URL"的消费者视角**：入库/入队字段里凡含 127.0.0.1/localhost 的地址，问一句"这条字符串最终被哪个网络命名空间解析？"。预览拉流（浏览器）与派发推流（引擎容器）共用一个字段时，重写只能发生在**派发出口**。
- **改 web 后端代码后若行为没变，别信 `--reload`**：Windows bind mount 下 uvicorn WatchFiles 经常丢失文件事件（无 reload 日志），`docker restart flysee-video-web-backend` 最可靠；验证是否生效可在容器内 `python -c` 直接调被改函数打印结果。
- 冒烟判据链（逐层证明）：`_to_engine_payload` 容器内输出 `rtmp://media:1937/...?sign=` → 引擎日志 `Output #0, flv, to 'rtmp://media:1937/...'` 且 0 refused → `[START TIMING] to_running=` → media FLV 带 sign 拉流 200 + 首块字节。

## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
