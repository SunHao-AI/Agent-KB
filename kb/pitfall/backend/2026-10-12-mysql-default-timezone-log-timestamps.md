---
id: kb-20261012-4a82
title: MySQL 墙钟需 --default-time-zone + --log_timestamps=SYSTEM 双参数
type: pitfall
domain:
- backend
tags:
- mysql
- time-zone
- log-timestamps
- container
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-04'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/时区与容器.md
---

# MySQL 墙钟需 --default-time-zone + --log_timestamps=SYSTEM 双参数

## 背景 / 现象

> 面向：`flysee_video_web` / `flysee-video-setting` 的 mysql 容器（mysql:8.0）。

**现象**：只设 `TZ=Asia/Shanghai` 后 `SELECT NOW()` 仍可能返回 UTC 或系统默认时区；`docker logs <mysql> 2>&1` 出的 `System` 行时间戳也是几小时前（UTC 后缀 `Z`）。

## 根因

**根因**：
- `TZ` 只影响 **mysqld 进程环境**（包括 `sysdate()` 之类依赖 OS 的），但建库时 `init-file` 创建 schema 的会话默认 `@@global.time_zone` 由服务端参数决定（常为 `SYSTEM`，落到宿主机 or UTC）；
- `log_timestamps` 默认 `UTC`：mysqld 错误日志/二进制日志的时间戳固定写 UTC，**不管 TZ 设什么**。

## 解决方案

**解决**：mysql 容器 `command` 追加（属启动参数，非 DDL，不触发 workspace DDL 限制）：
```yaml
command: --default-time-zone='+08:00' --log_timestamps=SYSTEM
```
- `+08:00` 形式而非 `Asia/Shanghai`：不依赖服务器端 timezone 表（`mysql.time_zone`）已加载，冷启动更安全；对上海等价；
- `--log_timestamps=SYSTEM` 让错误日志时间戳落到当前会话时区（=TZ），log 行不再是 `Z` 尾部。

## 验证

原文「验证」段(本会话 Task 2/Task 3 已验证): `SELECT @@global.time_zone g, NOW() db_now;` 期望 g=+08:00 且 db_now=Shanghai 当前; docker logs 的 ready for connections 行时间戳带 +08:00; docker inspect 的 Config.Cmd 含 --log_timestamps=SYSTEM。

**验证**（本会话 Task 2 / Task 3 已验证）：
- `SELECT @@global.time_zone g, NOW() db_now;` 期望 `g=+08:00`、`db_now` = Shanghai 当前；
- `docker logs flysee-video-web-mysql 2>&1 | Select-String "ready for connections"` 末两行时间戳带 `+08:00`；
- `docker inspect flysee-video-setting-mysql -format '{{json .Config.Cmd}}'` 含 `--log_timestamps=SYSTEM`。

## 适用边界与反例

**预防**：workspace 约定 mysql 容器**一律**带这两个启动参数，别只写 `TZ`；compose 默认值与本节点 time 格式锁定为 `Asia/Shanghai`；Repo 内不再写 `SET GLOBAL time_zone`（属 DDL，需用户授权）。

## 参考

- 源记录: `docs/known-pitfalls/backend/时区与容器.md`
