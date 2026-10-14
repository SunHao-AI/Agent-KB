---
id: kb-20261013-45b2
title: uvicorn `--reload` + SSE 常驻长连接：reload 永久停在 `Waiting for connections to close`，整后端假死
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-04'
updated: '2026-10-13'
severity: medium
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/构建与开发环境.md
---

# uvicorn `--reload` + SSE 常驻长连接：reload 永久停在 `Waiting for connections to close`，整后端假死

## 背景 / 现象

创建任务页一次性报 4 条前端日志，看着像两个接口慢：

```

AxiosError: timeout of 10000ms exceeded

[CreateTask] 环境预检请求失败: AxiosError: timeout of 10000ms exceeded

net::ERR_ABORTED https://127.0.0.1:15443/v1/algorithm-suites

net::ERR_ABORTED https://127.0.0.1:15443/v1/tasks/readiness

```

实际是**整个后端不响应**（`/v1/*` 全挂），与具体接口无关：`readiness` 最坏耗时 = engine 2s + media 1s ≈ 3s，`algorithm-suites` 正常 15–98ms，都在 axios 10s 之内。`ERR_ABORTED` 是 axios 超时后主动 `xhr.abort()` 的**结果**，不是原因——别顺着 `ERR_ABORTED` 去查 nginx。

## 根因

两层等待叠加成死结：

1. uvicorn `--reload` 收到变更 → 给旧 worker 发 SIGTERM → 走 graceful shutdown，**等在途连接自然结束**；

2. `/v1/sse/stream` 是 `while True` + `await request.is_disconnected()` 的常驻流式响应（浏览器 `EventSource` 经 nginx 长挂），**永远不会自然结束**；

3. 于是旧 worker 永久停在 `Waiting for connections to close`，而 reloader 要等旧 worker 退出才拉起新 worker → 两边互相等，后端整体假死。

4. 触发源是"内容未变但 mtime 变了"的写回：`WATCHFILES_FORCE_POLLING=true`（Windows bind mount 必需）下 watchfiles **只比 mtime 不比内容**，IDE 保存/格式化/black 写回同内容照样触发 reload。本次并行会话 22:5x–23:28 连续写回 `backend/core/logger.py`（MD5 与 HEAD 完全一致、git 干净），每次都白触发一轮 reload。

dev 命令原本没有任何优雅退出上限，所以这个死结没有出口。

## 解决方案

给 dev 的 uvicorn 加 `--timeout-graceful-shutdown`，让 reload 必然收敛（`docker/docker-compose.override.yml`）：

```yaml

command: ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "${FLYSEE_WEB_BACKEND_HOSTPORT:-17998}", "--reload", "--reload-dir", "backend", "--timeout-graceful-shutdown", "5"]

```

已卡死的现场靠 `docker restart flysee-video-web-backend` 恢复；**改 `command` 必须 `docker compose up -d backend` 重建容器**，`restart` 不会重读 compose 配置。

注：`docker stop/restart` 之所以还能从卡死中救回来，靠的是 docker 自己的 stop 宽限期（默认 10s）到点 SIGKILL；uvicorn **内部 reload 路径没有这层兜底**，只能靠 `--timeout-graceful-shutdown` 自限。加了该参数后 `docker restart` 也变快（实测 5s 超时 + ~3s 启动 ≈ 8s，日志会出现 `Cancel 1 running task(s), timeout graceful shutdown exceeded`，属预期而非异常）。

## 验证

```powershell

# 1) 占住一个在途请求不读完  2) touch 任意 backend/*.py 触发 reload  3) 看日志

# Shutting down

# Waiting for connections to close. (CTRL+C to force quit)

# ERROR  Cancel 1 running task(s), timeout graceful shutdown exceeded   ← 恰好 5s 后

# Finished server process [8]

# Started server process [17] → Application startup complete            ← 恢复

```

总不可服务窗口 ≈ 9.5s（超时 5s + 新 worker 启动 ~4s）。

## 适用边界

- **dev compose 里凡带 `--reload` 的服务，必须同时带 `--timeout-graceful-shutdown`**（本仓取 5s）。只要有 SSE / WebSocket / 长轮询等常驻连接，graceful shutdown 就无上界，reload 必然假死。

- 排查顺序固定为：**先判"慢还是死"**（直打后端端口看 `http=000` + 耗时打满），再看容器日志有没有 `Application startup complete`。跳过这步去查接口实现、去调大前端 `timeout` 都是治标——调大 timeout 只会把 10s 白等变成 30s 白等。

- reload 期间有约 **4s 不可服务窗口**，撞上的请求会超时。并行多会话在同一仓高频改 `backend/*.py` 时，前端偶发超时要先对时间点是否撞上 reload，别误判为接口 Bug。

- 别把"内容相同的重复保存"当无害：`WATCHFILES_FORCE_POLLING` 下它照样触发 reload。怀疑有隐形写入时用 hash + mtime 双观察（间隔采样 `Get-FileHash` / `LastWriteTime`），再配合 `git status`（内容未变则 git 干净）区分"真改动"与"空写回"。

- 改 `.py` 生效依赖 reload，但 `.env` / `Settings` 字段改动不触发 reload，须见本文件「修改 `.env` / Settings 字段不会触发热重载」条。

## 参考

- 源记录: `docs/known-pitfalls/backend/构建与开发环境.md` 「uvicorn `--reload` + SSE 常驻长连接：reload 永久停在 `Waiting for connections to close`，整后端假死」
