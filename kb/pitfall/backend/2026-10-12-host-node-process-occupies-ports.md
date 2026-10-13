---
id: kb-20261012-13e1
title: 宿主手起的 node media_server.js 抢占 1937/8082：media 容器 `ports are not available`
  起不来
type: pitfall
domain:
- backend
tags:
- port-conflict
- host-process
- netstat
- media-server
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

# 宿主手起的 node media_server.js 抢占 1937/8082：media 容器 `ports are not available` 起不来

## 背景 / 现象

> 面向：`dev-all.ps1 -WithMedia` 报 `exposing port TCP 0.0.0.0:8082 ... bind: Only one usage of each socket address`（2026-09-23）。

**现象**：`dev-all.ps1 -WithMedia` 中 web 栈全部 Running，唯独 `flysee-video-algorithm-media` 报 `Error response from daemon: ports are not available ... 8082 bind` 退出（此前该容器已 `Exited (137)`）；连带 web-frontend nginx 因 upstream media 不在网而 `Restarting` 循环（既有陷阱联动）。

## 根因

**根因**：宿主机上有一个**手工跑的** `node media_server.js`（e2e 验证期宿主直跑残留，`StartTime` 可佐证）占用 1937/8082 两个 LISTENING 端口。Docker Desktop 端口转发要绑宿主 `0.0.0.0:8082`，被宿主进程占住即 `bind` 失败——这与「容器间抢端口」不同，`docker ps` 里看不到占用者。

## 解决方案

**方案**：三步定位 + 清理：
1. `netstat -ano | Select-String ":8082.*LISTENING"` → 拿 PID；
2. `Get-Process -Id <PID>` + `(Get-CimInstance Win32_Process -Filter "ProcessId=<PID>").CommandLine` → 确认是宿主 node 而非 wslrelay/docker-proxy；
3. `Stop-Process -Id <PID> -Force` 后 `docker start flysee-video-algorithm-media`，nginx frontend 下一轮 restart 自愈。

## 验证

原文三步定位(实测): `netstat -ano` 拿 PID → `Get-Process` + `Win32_Process.CommandLine` 确认是宿主 node 而非 wslrelay/docker-proxy → `Stop-Process` 后 `docker start flysee-video-algorithm-media`, nginx frontend 下一轮 restart 自愈。

## 适用边界与反例

**要点**：
- 宿主直跑 media_server.js 与容器化 media **互斥**（同占 1937/8082），e2e/调试用完宿主进程必须收尾，否则下次 `dev-all` 必炸。
- media 容器 `Exited (137)`（OOM/SIGKILL）后 compose `up` 只会 `Starting` 再失败——先修端口冲突再看容器本身。

## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
