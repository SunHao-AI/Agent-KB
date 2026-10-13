---
id: kb-20261012-6872
title: 跨 compose 栈打通网络致 service 名 DNS 歧义（web 容器被打到 setting-mysql）
type: pitfall
domain:
- backend
tags:
- docker-network
- dns
- service-alias
- host-docker-internal
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

# 跨 compose 栈打通网络致 service 名 DNS 歧义（web 容器被打到 setting-mysql）

## 背景 / 现象

**现象**（2026-09-23 方案 B E2E）：为让 web backend 能访问 setting backend（两栈网络独立：`flysee-video-web_default` vs `flysee-video-setting_default`），执行 `docker network connect flysee-video-setting_default flysee-video-web-backend`。随后 web backend 所有 DB 读写报 `pymysql.err.OperationalError (1045, "Access denied for user 'flysee'@'172.18.0.4'")`，但 `/health` 仍 200、uvicorn 进程正常；license 自动续期日志刷 `Name or service not known`。

## 根因

**根因**：两栈都有同名 service 别名 `mysql` / `redis`。web backend 加入 setting 网络后，`DATABASE_URL=mysql+pymysql://...@mysql:3306/...` 里的 `mysql` 在 Docker 内嵌 DNS 解析时**命中的是 setting-mysql**（而非本栈 web-mysql），web 的 `flysee` 用户在 setting-mysql 上不存在 → 1045。`server_url` 用容器名 `flysee-video-setting-backend` 时也偶发解析不稳。这是共享 service 别名 + 双网络叠加的必然歧义，与解析顺序/加入顺序相关。

## 解决方案

**解决**：**禁止把容器加入另一栈网络来跨栈访问**。改用宿主端口 + `host.docker.internal`：
1. setting backend 已有宿主端口映射（`8099:8099`），web 容器经 `host.docker.internal:8099` 访问；
2. web 库 `client_config.server_url` 改为 `http://host.docker.internal:8099`；
3. `docker network disconnect flysee-video-setting_default flysee-video-web-backend` 恢复单网络。
Docker Desktop（WSL2）下 `host.docker.internal` 解析为 `192.168.65.254`，可直达宿主映射端口。

## 验证

原文「防踩」判定(实锤): 1045 报错的 host 段(`'flysee'@'172.18.0.4'`)是 setting 网络网段而非 web 网络网段; `docker inspect` 确认容器被误挂两个网络; disconnect 恢复单网络。

## 适用边界与反例

**防踩**：
- 判定 DNS 歧义：1045 的 host 段（`'flysee'@'172.18.0.4'`）是 setting 网络网段而非 web 网络网段即实锤；`docker inspect` 看容器 `Networks` 是否被误挂两个网络。
- 跨 compose 栈互访一律走 `host.docker.internal:<宿主映射端口>`，各栈 service 别名（`mysql`/`redis`）天然只在本网内有效，跨网必冲突。
- 宿主端口避开占用：web 占 8099? 否——setting backend 用 8099、web backend 17998、setting mysql 13306、setting redis 6390（web redis 6380），规划见各仓 `docs/port-configuration.md`。

## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
