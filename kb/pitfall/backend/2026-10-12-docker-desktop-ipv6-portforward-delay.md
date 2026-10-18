---
id: kb-20261012-bfb7
title: Docker Desktop 端口转发：重建容器后 localhost(IPv6) 通道偶发超时，须等转发重新编程（2026-09-21）
type: pitfall
domain:
- backend
tags:
- docker-desktop
- ipv6
- port-forward
- wslrelay
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-22'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/测试与开发环境.md
---

# Docker Desktop 端口转发：重建容器后 localhost(IPv6) 通道偶发超时，须等转发重新编程（2026-09-21）

## 背景 / 现象

> 面向：Windows + WSL2 后端 Docker Desktop，用 `localhost` 访问容器映射端口（`localhost` 同时解析 `127.0.0.1` 与 `::1`）。

**现象**：`up -d --build` 重建 frontend 后，`127.0.0.1:15443` 立刻 200，但 `[::1]:15443` / `localhost:15443` 连接超时（curl 28），反复试几十秒内自愈。`netstat` 显示 `0.0.0.0` 与 `[::]` 由 `com.docker.backend` 监听，`[::1]` 单独由 `wslrelay.exe` 监听。

## 根因

**根因**：宿主端口转发由 `com.docker.backend`（IPv4 通配）+ `wslrelay`（IPv6 loopback 单独 relay）两套通道分别编程。容器 recreate 时 IPv4 通道先就绪，**IPv6 relay 通道重建有延迟**，这期间 `[::1]` 能完成 TCP 握手（relay 在监听）但后续流量无出口 → 超时而非拒绝。与「`Created` 容器被后续 `up` 直接 start 时宿主端口转发不重新编程，须 `--force-recreate`」是同一族问题。

## 解决方案

**解决 / 结论**：
1. **不是 nginx 也不是应用问题**，无需改 compose / hosts。等端口转发编程完成（本次约数十秒）后 IPv6 通道稳定（复测 IPv4/IPv6 各 8/8 全 200）。
2. 排查顺序：先 `netstat -ano | Select-String ":<port>"` 确认 `com.docker.backend` 与 `wslrelay` 都在 LISTENING；再分别用 `127.0.0.1` 与 `[::1]` 打同一 URL 对比——**只有 `[::1]` 挂而 `127.0.0.1` 通**即本问题，不必怀疑证书、CORS、nginx。
3. 若长时间（分钟级）不自愈：`docker restart <container>` 或 `docker compose ... up -d --force-recreate <service>` 重新触发转发编程；仍无效再考虑重启 Docker Desktop。
4. **不要**为了绕开而往 `hosts` 里写 `127.0.0.1 localhost`：这只掩盖 IPv6 通道，且 `wslrelay` 的 IPv6 监听残留会让 `::1` 上其他端口行为更难解释。

## 验证

原文实测: 等端口转发编程完成(本次约数十秒)后复测 IPv4/IPv6 各 8/8 全 200; 判据为 `127.0.0.1` 通而 `[::1]` 挂(curl 28 超时非 7 拒绝)即本问题。

## 适用边界与反例

**防踩**：`curl` 报 28（超时）与 7（拒绝）要分清——28 说明端口有监听但转发未就绪（本问题），7 才是没人监听（端口没映射 / 容器没起）。

## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
