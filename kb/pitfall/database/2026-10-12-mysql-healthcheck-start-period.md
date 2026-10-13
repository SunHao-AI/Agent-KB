---
id: kb-20261012-795e
title: MySQL 冷启动初始化超过健康检查窗口，导致 `dev.ps1 start` 整链路失败
type: pitfall
domain:
- database
tags:
- mysql
- docker
- healthcheck
- devops
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-12'
updated: '2026-10-12'
related:
- kb-20261012-08b8
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/database/约束与迁移.md
---

# MySQL 冷启动初始化超过健康检查窗口，导致 `dev.ps1 start` 整链路失败

## 背景 / 现象

`dev.ps1 start` 报 `dependency failed to start: container flysee-video-setting-mysql is unhealthy`; 随后 3 次重试每次 0.5 秒就失败, 最终 `启动失败`。但稍后 `docker ps` 里 mysql 自己变成 `Up (healthy)`, 前后端只是停在 `Created`。

## 根因

四个因素叠加, 均非配置错误:

1. **判定窗口小于初始化耗时**: healthcheck 只有 `interval:10s + retries:5` ≈ 50s, 且无 `start_period`; 全新卷首次初始化(建系统表 + 跑 `docker/init/*.sql`)在 4C4G 的 WSL2 上实测容器启动后 90~100s 才 `ready for connections`(仅 InnoDB init 就 50s+)。
2. **宿主机资源不足放大耗时**: `docker info` 仅 4 CPU / 4GB, mysql(1g)+backend(512m)+frontend(512m)+redis 并发冷启动互抢 CPU/IO, 日志里 redis 起容器花了 212s、mysql 从 `up` 到真正 Started 隔了 3.5 分钟。
3. **backend 硬依赖 healthy**: `docker-compose.dev.yml` 的 `depends_on: mysql: condition: service_healthy`, mysql 一被标 unhealthy, 整条 `up` 立刻失败。
4. **盲重试无效**: 失败时 mysql 容器仍在运行、只是 unhealthy, `docker compose up -d` 对"依赖已存在且不健康"不等待, 直接返回失败; 原来的 `Start-Sleep 15` × 3 = 45s 短于 mysql 转 healthy 的剩余时间, 三次全废。

## 解决方案

两层, 已落地:

- **A. 给 mysql healthcheck 加 `start_period`**(`docker-compose.override.yml`): 宽限期内探测失败不计入 `retries`, 等价把判定窗口放宽到 `start_period + interval*retries`。

```yaml
healthcheck:
  test: ["CMD-SHELL", "mysqladmin ping -h localhost -u root -p$$MYSQL_ROOT_PASSWORD"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 180s   # 覆盖冷启动初始化，避免途中被误判 unhealthy
```

- **B. 脚本失败后先等依赖 healthy 再重试**(`scripts/dev.ps1` 的 `Get-ServiceHealth` / `Wait-ServiceHealthy`): 全量 `up` 失败后先 `docker compose up -d mysql` 并轮询 `.State.Health.Status` 到 healthy, 再重试全量 up; 超时则直接失败并提示查 `docker compose logs mysql`, 不再做无意义的盲重试。

```powershell
docker compose @composeArgs ps -a -q $Service          # 拿容器 id（不硬编码 container_name）
docker inspect -f "{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}" $id
```

## 验证

排查手段: `docker inspect <mysql> --format "{{json .State.Health}}"` 看 `FailingStreak` 与各次探测输出; `docker logs --timestamps` 对比 `InnoDB initialization has started/ended` 与 `ready for connections` 的时间差, 即可判断是"初始化慢"而非"配置错"。

## 适用边界与反例

- 误判提醒: `.env` 的 `FLYSEE_DATABASE_CONT_PORT=13306` 与本故障无关——它在 `backend/core/config.py` 映射到 `mysql_host_port`(宿主直连用), 容器内走 `mysql` + `FLYSEE_SETTING_MYSQL_CONTAINERPORT`。
- 资源侧缓解: Docker Desktop 提到 6 CPU / 8GB 可显著缩短冷启动; 但 A+B 已能消除该失败, 不必依赖加资源。

## 参考

- 源记录: `docs/known-pitfalls/database/约束与迁移.md` (条目对应变更 2026-09-12)
