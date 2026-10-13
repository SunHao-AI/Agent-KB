---
id: kb-20261012-2462
title: WSL2 容器内 h264_nvenc "Cannot load libnvidia-encode.so.1"：缺 NVIDIA_DRIVER_CAPABILITIES，注入
  all 即通
type: pitfall
domain:
- backend
tags:
- nvenc
- nvidia-container-toolkit
- runtime-probe
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-23'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/测试与开发环境.md
---

# WSL2 容器内 h264_nvenc "Cannot load libnvidia-encode.so.1"：缺 NVIDIA_DRIVER_CAPABILITIES，注入 all 即通

## 背景 / 现象

> 面向：Docker Desktop(WSL2) 下 GPU 容器要用 NVENC 硬编推流的场景（本例 `flysee_video_algorithm` engine ffmpeg 推流卡顿，2026-09-23）。

**现象**：engine 容器 CPU 飙到 **503%**（ffmpeg `libx264 ultrafast` 960x720@30 软编打满多核）、`speed=0.1~1.2x` 勉强追实时 → 前端预览严重卡顿。容器内 `ffmpeg -c:v h264_nvenc` 报 `Cannot load libnvidia-encode.so.1`；`ldconfig -p` 里只有 `libnvidia-ml/gpucomp`，没有 encode/cuvid。

## 根因

**根因**：nvidia-container-toolkit 默认按 `NVIDIA_DRIVER_CAPABILITIES=compute,utility` 注入驱动库子集，**不含 video 类的 `libnvidia-encode.so.1`**。compose 里 `deploy.resources.reservations.devices` 只给了 `driver=nvidia` + `count=all`（capability 只有 `compute,utility`），没设 env。宿主 WSL2 driver 本身是带 encode 库的（官方支持 WSL2 NVENC）。

## 解决方案

**方案**（三步全实证）：
1. compose engine 环境注入 `- NVIDIA_DRIVER_CAPABILITIES=all`（官方 WSL2 方案即 all 或加 video）→ `docker compose ... up -d engine` **重建**容器（env 非热更）；
2. 编码器改**探测式选择**（`tools.create_ffmpeg_pipe`）：进程内跑一次 `ffmpeg -f lavfi -i testsrc -c:v h264_nvenc -f null -` 实测（比查库文件可靠，能识别 driver/会话超限）；OK → `h264_nvenc -preset p1 -tune ll -rc vbr -cq 26 -b:v 4M -g fps -bf 0`，失败 → 原 libx264 参数原样回退。效果：CPU 503%→229%，`encoder: Lavc h264_nvenc` 生效；
3. **探测帧尺寸不能太小**：`size=64x64` 会让 NVENC 报 `InitializeEncoder failed: Frame Dimension less than the minimum`（**误判不可用**），`256x256` 实测 OK——探测失败先手动复跑同命令看真因，别信表面 exit code。

## 验证

原文「方案」段标注三步全实证: 注入 all 重建后 `encoder: Lavc h264_nvenc` 生效, CPU 503%→229%; 探测帧尺寸 64x64 会误报 Frame Dimension less than minimum, 256x256 实测 OK。

## 适用边界与反例

**要点**：
- 容器 GPU「能推理」≠「能编解码」：`compute,utility` 只保证 CUDA/cuBLAS；NVENC/NVDEC/CUVID 要 **video** capability。
- compose 改动（environment/devices）必须 `up -d` 重建；而 engine `app/` 无 bind mount → 重建后**之前 docker cp 进去的代码会丢**，需重新 cp（见同文件「engine 代码打包进镜像」条目）。
- 探测式（runtime probe）优于配置式（env 开关）：NVENC 有会话数/显存/driver 多重限制，静态配置会"配置说支持、运行时炸"；probe 失败自动回落，部署零配置。
- 验证推流是否真通，别看 ffmpeg 中间帧统计（`frame= 125 q=...` 会持续滚动），看**下游**：media FLV 带 sign 拉流 5s 累计字节是否持续增长。
- WSL2 容器 NVENC 首帧后偶发 `Error submitting a packet to the muxer: End of file` 且 engine 有 503→229% 但 CPU 仍高：**不代表硬编没生效**（`encoder: h264_nvenc` + GPU util 57% 是生效铁证），残留 muxer EOF 是上游 rawvideo 断供（GPU 准入 tight 反复拒启的窗口期）。

## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
