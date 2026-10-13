---
id: kb-20261012-7682
title: 算法 engine 代码打包进镜像（无 app/ bind mount）：改码后 docker restart 不生效
type: pitfall
domain:
- backend
tags:
- image-copy
- bind-mount
- inspect-probe
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-23'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/测试与开发环境.md
---

# 算法 engine 代码打包进镜像（无 app/ bind mount）：改码后 docker restart 不生效

## 背景 / 现象

> 面向：`flysee_video_algorithm` engine 容器（E2E 修复验证 / 2026-09-23），及一切"compose 只挂数据卷、不挂源码"的服务。

**现象**：宿主改了 `app/services/detect_service.py`，`docker restart flysee-video-algorithm-engine` 后容器仍跑旧代码——`inspect.getsource` 查不到新增函数，误以为修复无效。

## 根因

**根因**：engine 的 compose（`docker/docker-compose.app.yml`）volumes 只挂 `logs/images/videos/model_cache` 四个数据目录，**`app/` 源码是 COPY 进镜像的**（区别于 web backend 的 bind mount + WatchFiles 热重载）。restart 只是重启进程，镜像层不变。

## 解决方案

**方案**：
- dev 快速验证：`docker cp <宿主文件> 容器:/app/<对应路径>` + `docker restart`——秒级生效，但**下次镜像重建即丢**，只当临时冒烟手段；
- 正式生效：`docker compose -f docker/docker-compose.app.yml build engine && up -d engine`（镜像巨大，耗时长）；
- 验证"容器里到底是哪版代码"的可靠探针：`python -c "import inspect, app.services.detect_service as m; print('_await_start_ack' in inspect.getsource(m.DetectService))"` 或 `docker inspect --format {{json .Mounts}}` 看有没有对应 bind。

## 验证

原文方案段验证探针(实测): `python -c "import inspect, app.services.detect_service as m; print('_await_start_ack' in inspect.getsource(m.DetectService))"` 或 `docker inspect --format {{json .Mounts}}` 看有没有对应 bind, 以容器内实际加载源码为准。

## 适用边界与反例

**要点**：
- 判断"改动是否生效"永远以**容器内实际加载的源码**为准（inspect/文件 grep），不要信"我改了宿主文件 + 我重启了容器"。
- PowerShell → `docker exec sh -c` 的引号嵌套极易碎（`'` 内 `\"` 会被剥错层）；带引号的多行 Python 用 **stdin 管道**最稳：`'代码' | docker exec -i 容器 python -`。

## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
