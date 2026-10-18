---
id: kb-20261012-4a12
title: '`build: context:` 跨仓镜像复用风险（独立条目，两仓都要打同一种 patch）'
type: pitfall
domain:
- backend
tags:
- compose-build
- cross-repo
- dockerfile
- tzdata
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-04'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/时区与容器.md
---

# `build: context:` 跨仓镜像复用风险（独立条目，两仓都要打同一种 patch）

## 背景 / 现象

> 面向：任意两个仓共用前端 / 后端 Dockerfile 的 workspace 类型工程。

**现象**：patch A 仓 `frontend/Dockerfile` 后，A 仓容器 `date = CST 2026` 但 B 仓容器 `date = UTC 2026`，docker logs 看 B 仓 Vite dev 日志时间戳都是 `09:3x`（与上海 17:3x 差 8h）；git diff A 仓显示 `RUN apk add --no-cache tzdata` 已落，B 仓完全无对应改动——但人肉观感上"Dockerfile 应该是一样的"。

## 根因

**根因**：docker compose 的 `build: context: ../frontend` 是**相对 compose file 自身**解析的：`flysee_video_web/docker/docker-compose.override.yml` 的 `context: ../frontend` 实际指向 `flysee_video_web/frontend/`（不指向 `flysee-video-setting/frontend/`）。两仓各自维护 `frontend/Dockerfile`，文件内容可能复制粘贴而一致，但 runtime 上**完全独立**，`docker compose up` 不会跨仓发现另一仓的镜像构建。

## 解决方案

**解决**：对所有 workspace 拥有 frontend/Dockerfile 的仓**统一模板**——每个仓自己的 `frontend/Dockerfile` 都要 `RUN apk add --no-cache tzdata`（在 `COPY . .` 之前）。本次单位：

```dockerfile
# 在"先复制依赖清单，利用构建缓存 COPY package*.json ./ + RUN npm install"之后插一行
RUN apk add --no-cache tzdata
```

## 验证

原文「现象」段实录: patch A 仓后 A 仓容器 date=CST 但 B 仓容器 date=UTC(差 8h), git diff 证实 B 仓完全无对应改动; 预防手法为每个 frontend/backend 容器都跑 `docker exec <container> date` 廉价校验。

## 适用边界与反例

**预防**：
- workspace 中新增仓若有 `node:*-alpine` frontend Dockerfile，**仓内 grep `node:.*-alpine` 命中后做模板检查**：必须 `apk add --no-cache tzdata` + 同一 compose 注释里说"补 tzdata"；
- `docker exec <container> date` 是廉价校验——**Container date 必须在每个 frontend / backend 容器都跑一遍**，不要假设"A 仓对了 → B 仓自动对"。

## 参考

- 源记录: `docs/known-pitfalls/backend/时区与容器.md`
