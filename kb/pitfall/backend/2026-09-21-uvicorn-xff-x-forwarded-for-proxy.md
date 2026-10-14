---
id: kb-20261013-a420
title: 反代信任链陷阱：uvicorn 取 XFF **首项**，追加式 X-Forwarded-For + --proxy-headers = 伪造绕过闸门（D32）
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-21'
updated: '2026-10-13'
severity: high
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/认证与锁屏.md
---

# 反代信任链陷阱：uvicorn 取 XFF **首项**，追加式 X-Forwarded-For + --proxy-headers = 伪造绕过闸门（D32）

## 背景 / 现象

> 面向：`frontend/nginx.conf` + `Dockerfile` CMD + `docker/docker-compose.override.yml` command。第四十六轮走查 2026-10-09，收口 D31 遗留风险。
**关键不变式**：`--forwarded-allow-ips` 的信任段必须恰好是"反代所在网段"——写 `*` 等于信任一切来源（回到可伪造）；写太窄（如只信 nginx 单 IP）则 docker 网段重建后 IP 漂移、静默退回 nginx IP 桶。网段级（172.16/12）是 compose 网络的稳定口径。

## 根因

uvicorn `--proxy-headers` 取 XFF 的第一个逗号项覆盖 `request.client.host`，而 nginx 惯用的 `$proxy_add_x_forwarded_for` 是追加式——客户端自带的 `X-Forwarded-For: 8.8.8.8` 会排在最前。两个各自正确的配置组合后，后端看到的来源 IP 等于攻击者自报的伪造值，限速闸门每换一个假头即换一个桶，开了信任链反而比不开更糟。

## 解决方案

- nginx（单层反代无保留链需求）：`proxy_set_header X-Forwarded-For $remote_addr;`——**覆盖式**，客户端带的 XFF 被整体替换；

- uvicorn（Dockerfile CMD 与 compose override **两个启动点同口径**，漏一个该环境就是洞）：`--proxy-headers --forwarded-allow-ips '172.16.0.0/12'`——只信 docker 私网段来的转发头，段外直连忽略头退回真实 TCP 对端（纵深防御：生产 backend 本不发布宿主端口）;

- `X-Real-IP` 保持 `$remote_addr`（uvicorn 实际优先读 XFF，两空头一致最稳）。

## 验证

经 nginx 伪造 `XFF: 8.8.8.8` 连打 5 次 → 锁定键必须是**真实来源 IP**（如 172.19.0.1）而非 8.8.8.8；即"伪造失效"与"还原生效"是同一件事的两面，用锁定键名做观测点最直接。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/backend/认证与锁屏.md` 「反代信任链陷阱：uvicorn 取 XFF **首项**，追加式 X-Forwarded-For + --proxy-headers = 伪造绕过闸门（D32）」
