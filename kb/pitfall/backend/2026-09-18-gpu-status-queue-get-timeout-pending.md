---
id: kb-20261013-4ddf
title: GPU 检测子进程冷启动 > 30s：`status_queue.get(timeout=30)` 误判失败，孤儿进程照跑但状态永卡 pending
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-18'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: high
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/任务派发与算法联动.md
---

# GPU 检测子进程冷启动 > 30s：`status_queue.get(timeout=30)` 误判失败，孤儿进程照跑但状态永卡 pending

## 背景 / 现象

生产形态容器（compose 起算法镜像）真实创建任务后，日志一切正常、输出流确实在推（`ffprobe` 出 h264 流）、检测图片落盘且带框，但 `aivis_tasks.status` 恒为 `pending`、`start_at` 为 NULL；容器里检测子进程、拉流/推流 ffmpeg 全都活着，只是父进程链早已不管它（PPid=1 孤儿）。

## 根因

1. **超时太短**：`DetectService._start_yolov` 里 `status_queue.get(timeout=30)` 等子进程回 `success`。

   但"success"是在 `stream_loop` **推出第一帧**时才 `put_nowait`——此前子进程要走完

   模型解密 → `spawn` 重新 import torch/ultralytics（GPU wheel 首次导入极慢）→

   TRT 引擎 `deserialize` → RTMP 拉流建连 → 首帧推理。弱卡（GTX 1660 Ti）+ 首次冷启动

   实测 **3~4 分钟**，30s 必然 `queue.Empty`。

2. **清理杀不掉子进程**：`_cleanup_failed_start` 用 `psutil.Process(pid).terminate()`（SIGTERM），

   而 `Detector` 在 `initialize` 里注册的线程/信号处理链吞掉 SIGTERM，进程不死，继续拉流推流成孤儿。

3. **状态不回写**：超时分支只 `_cleanup_failed_start` + 返回 error dict，既不 `AivisTask.update_status`，

   返回值又被 `TaskConsumer` 忽略（见上文"TaskConsumer 吞异常"条目）。于是 DB 永远 pending，

   而真实世界推理在跑——**状态与事实永久漂移**。

## 解决方案

- 超时改为可配 `settings.detect_start_timeout`（默认 300s），别用裸 `timeout=30`；

- `_cleanup_failed_start` 改用 `_kill_process_tree(pid)`（`children(recursive=True)` + `kill()` SIGKILL），

  与 `stop()`/`_process_reaper` 用同一套强杀，杜绝 terminate 被吞；

- （建议后续）超时/失败分支也回写 `AivisTask.update_status(task_id, "stopped", close_reason=<非0>)`，

  别让任何启动失败路径把行留在 pending。

## 验证

弱卡（GTX 1660 Ti）+ 首次冷启动实测 **3~4 分钟**，30s 必然 `queue.Empty`；旁证（`ffprobe` 出帧、出框图片、`docker top` 看 PPid=1）证明推理实际在跑，把问题定位到状态回写而非推理失败。

## 适用边界

- **"成功"信号不能在链路最深处首次产生**再回传——确认点越靠后，超时窗口必须越长，

  否则健康进程被判死。要么把成功信号提前到"进程已就绪"（如引擎加载完即报 ready），

  要么把超时按最坏冷启动设定并可配。

- 子进程清理一律 **SIGKILL 进程树**，不要 `terminate()`：凡注册了信号处理/守护线程的进程，

  SIGTERM 都可能被吞。

- 判断"任务到底跑没跑"别只看 `status` 字段：对照**旁证**——输出流 `ffprobe` 有无帧、

  `images/<task_id>/` 有无新图、容器内 `/proc` 有无对应 python+ffmpeg。本例正是靠

  出框图片证明推理正常，才把问题定位到"状态回写"而非"推理失败"，避免误改推理链。

- `dmesg`/`docker inspect` 之外，`docker top <容器>` 或 `/proc/<pid>/status` 的 `PPid`

  是发现孤儿子进程（`PPid=1`）的最直接手段。

## 参考

- 源记录: `docs/known-pitfalls/backend/任务派发与算法联动.md` 「GPU 检测子进程冷启动 > 30s：`status_queue.get(timeout=30)` 误判失败，孤儿进程照跑但状态永卡 pending」
