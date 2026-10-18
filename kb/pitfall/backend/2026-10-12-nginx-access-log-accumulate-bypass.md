---
id: kb-20261012-97d8
title: nginx 官方镜像 http 级 `access_log main` 与自定义脱敏格式**累加双写**：SEC-19 脱敏被镜像默认配置旁路, query
  票据泄漏进日志
type: pitfall
domain:
- backend
tags:
- nginx
- access-log
- masking
- security
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-23'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/测试与开发环境.md
---

# nginx 官方镜像 http 级 `access_log main` 与自定义脱敏格式**累加双写**：SEC-19 脱敏被镜像默认配置旁路, query 票据泄漏进日志

## 背景 / 现象

> 面向：`flysee_video_web` / `flysee-video-setting` 两仓 `frontend/nginx.conf`（2026-09-23 修复）。

**现象**：web-frontend 容器 access 日志**同一请求出现两行**（格式不同：一行脱敏 `GET /v1/tasks/readiness HTTP/1.1`, 一行镜像默认 main 格式带完整请求行）。更严重的是 main 行含 `$request`（带 query）——`GET /v1/sse/stream?ticket=e381fd1a…` 的**一次性 SSE 票据原样落盘**, http 级 `sec19_noargs` 脱敏形同虚设。

## 根因

**根因**：nginx `access_log` 继承规则是**同级别累加、子级别遮蔽**——nginx 官方镜像自带 `nginx.conf` 在 `http{}` 里已有一条 `access_log /var/log/nginx/access.log main;`, 我们的 `default.conf`（include 进同一 `http{}`）再写一条 http 级 `sec19_noargs` → **两条同时生效各写一行**。SEC-19 改造只在 http 级追加, 从未压掉镜像默认那条。

## 解决方案

**解决**（两仓 nginx.conf 同步修）：在 80 和 443 两个 `server{}` 内**各自声明** `access_log /var/log/nginx/access.log sec19_noargs;`——server 级 access_log 会**遮蔽** http 级的全部条目（main+sec19 都不再继承）；http 级那条仅作无 server 覆盖时的兜底。改后 `docker compose build frontend; up -d frontend`（nginx.conf 经 `Dockerfile.prod` COPY 为 template, **必须重建镜像**）。

## 验证

原文「验证口径(实测)」: `curl "https://127.0.0.1:15443/v1/tasks/readiness?ticket=SECRET_PROBE_456"` → 容器日志仅一行脱敏格式(方法+uri 无 query), 全文 grep SECRET_PROBE 零命中; `nginx -t` 通过。

**验证口径（实测）**：`curl "https://127.0.0.1:15443/v1/tasks/readiness?ticket=SECRET_PROBE_456"` → 容器日志仅一行 `"GET /v1/tasks/readiness HTTP/1.1" 401`（方法+uri 无 query）, 全文 grep `SECRET_PROBE` 零命中; `nginx -t` 通过。

## 适用边界与反例

**要点**：
- **nginx 指令分「累加型」与「覆盖型」**：`access_log`/`error_log`/`auth_basic_user_file` 等在同级别是累加, 一旦父级（尤其第三方基础镜像的内置配置）已有声明, 想独占必须在**子级别（server/location）重新声明**——子级出现即整组替换, 老条目不再继承。
- **在别人的基础镜像上做安全加固, 必须 diff 镜像内置配置**：`docker exec <c> grep -rn access_log /etc/nginx/nginx.conf` 一条命令就能发现旁路; 只在"自己那半"写合规配置 ≠ 全局合规。
- 判定"双份日志是不是反代链叠加"别看行数, 看**格式差异**: 两行格式不同 = 两条 access_log 指令; 格式完全相同 = 代理链多级各记一次。
- setting 仓同源缺陷本次一并修（其前端为 dist 冻结型镜像, 下次 `-Build` 时生效）。

## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
