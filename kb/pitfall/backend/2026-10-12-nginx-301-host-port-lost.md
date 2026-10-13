---
id: kb-20261012-d76d
title: nginx `return 301 https://$host` 丢宿主端口，本地 http 入口跳向无人监听的 443（2026-09-21）
type: pitfall
domain:
- backend
tags:
- nginx
- redirect
- envsubst-template
- port-mapping
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-22'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/测试与开发环境.md
---

# nginx `return 301 https://$host` 丢宿主端口，本地 http 入口跳向无人监听的 443（2026-09-21）

## 背景 / 现象

> 面向：web 仓前端 nginx（SEC-10：80 只做 `/health` 探活 + 301 跳 https，业务全在 443），本地宿主端口非 443（默认 15173/15443）。

**现象**：浏览器访问 `http://localhost:15173/` 显示"服务不可用"。`curl -I` 看到 `301 → https://localhost/`（**无端口**），落到宿主 443——本地没人监听，连接被拒/超时。

## 根因

**根因**：`$host` 只含主机名，**不含 `Host` 头里的端口**。生产宿主 443 直映射容器 443 时 `https://$host` 恰好正确；本地宿主端口错开（15443）后 301 目标就指错了。compose 注释里原本只写"本地请直接访问 https://localhost:15443/"作为绕法，未真正修复跳转。

## 解决方案

**解决**（nginx 官方镜像 envsubst 模板机制）：
1. `frontend/nginx.conf` 跳转改为带端口变量：
   ```nginx
   return 301 https://$host:${FLYSEE_TLS_PUBLIC_PORT}$request_uri;
   ```
2. `frontend/Dockerfile.prod` 必须以 **template 身份**放置，交给 nginx entrypoint 的 `20-envsubst-on-templates.sh` 渲染：
   ```dockerfile
   COPY nginx.conf /etc/nginx/templates/default.conf.template   # 不是 /etc/nginx/conf.d/
   ```
3. `docker-compose.override.yml` frontend 注入宿主 TLS 端口（与 `ports` 映射同源，避免两处漂移）：
   ```yaml
   - FLYSEE_TLS_PUBLIC_PORT=${FLYSEE_WEB_FRONTEND_TLS_HOSTPORT:-15443}
   ```

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

**防踩**：
- envsubst 只替换**环境中已定义**的变量，`$host` / `$request_uri` 等 nginx 运行时变量不会被吃掉——这是本方案安全的前提。若想显式限定白名单可配 `NGINX_ENVSUBST_FILTER`。
- 生产把宿主 443 直映射容器 443 时注入 `443` 即可（`https://host:443` 等价默认端口，无害），不必改配置。
- **改 nginx.conf 属于 dist 冻结型镜像改动，必须重建镜像**（`up -d --build frontend`），`docker restart` 不生效（模板在镜像层）。
- 判定是不是这个坑：`curl -I http://127.0.0.1:<http口>/` 看 `Location` 是否带上了 TLS 宿主端口。

## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
