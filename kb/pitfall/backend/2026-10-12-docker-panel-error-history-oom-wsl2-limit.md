---
id: kb-20261012-31a7
title: Docker Desktop 面板显示容器 Error 但当前 healthy：历史 OOM 记录, 根因是内存超 WSL2 限额
type: pitfall
domain:
- backend
tags:
- docker
- oom-kill
- wsl2
- mem-limit
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-23'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/性能与容错优化.md
---

# Docker Desktop 面板显示容器 Error 但当前 healthy：历史 OOM 记录, 根因是内存超 WSL2 限额

## 背景 / 现象

**现象**：Docker Desktop 里 `flysee-video-algorithm-engine` 显示红色 Error / Exited(137), 但 `docker ps` 当前又是 `Up (healthy)`——面板与实时状态"矛盾"。

## 根因

**根因**：面板 Error 来自**上一次容器实例的历史退出记录**, 不是当前实例。`docker events --filter event=die` 抓到多次 `exitCode=137`（=128+9=SIGKILL, 且 `docker inspect State.OOMKilled` 或宿主侧 OOM killer 触发）。engine 容器无 `mem_limit`（`HostConfig.Memory=0`, 继承 WSL2 整机默认 ~3.8GB）, 当「任务推理 + AI 直播 sim_push 第二路推理」双份 TensorRT 引擎 + ffmpeg 同时在内存, 撑破 WSL2 内存限额 → 被杀 → 容器进入 Exited/Error → `restart: unless-stopped` 拉起新实例变 healthy, 于是"面板 Error + 当前 healthy"并存。

## 解决方案

**方案/规避**：
- 弱卡/低内存环境**避免同时开「文件直喂任务」+「AI 直播 sim_push」**（两路完整推理实例）；预览用任务自带流, 不必再 sim_push。
- 需要硬隔离时给 engine 设 `mem_limit` 并在应用侧限制并发推理路数（`max_tasks` / `gpu_free_mb_per_task` 准入阈值）, 宁可显存准入拒绝也不要整机 OOM 被杀。

## 验证

原文「排查三步」段(可复核命令): `docker inspect` 看当前实例 `State.OOMKilled`、`docker events --filter event=die` 抓到多次 `exitCode=137`, 关联多路推理/大 .engine 加载的内存峰值。

## 适用边界与反例

**排查三步**（面板报 Error 但怀疑非当前故障时）：
1. `docker inspect --format "{{.State.Status}} {{.State.ExitCode}} OOM={{.State.OOMKilled}}"` 看**当前**实例；
2. `docker events --filter container=NAME --filter event=die`（流式, 记得带 `--until` 或自行停）看历史 `exitCode=137`；
3. 关联负载：137 多发生在显存/内存峰值（多路推理、大 .engine 加载、AI 直播叠加）。

- **改码后 `docker restart` 不会更新镜像内代码**（engine 源码是 `COPY` 进镜像, 非 bind mount）：dev 用 `docker cp` 进容器 + restart 临时生效, **固化到镜像须走 `scripts\build-engine.ps1`**（见下条：`docker compose build` 对本镜像不可用）。

## 参考

- 源记录: `docs/known-pitfalls/backend/性能与容错优化.md`
