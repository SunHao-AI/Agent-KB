---
id: kb-20261012-5a0c
title: 容器 env_file 不等于 bind mount 导致 JWT HMAC key 为空
type: pitfall
domain:
- backend
tags:
- docker
- compose
- env
- jwt
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-01'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/鉴权与会话.md
---

# 容器 env_file 不等于 bind mount 导致 JWT HMAC key 为空

## 背景 / 现象

> 面向：`flysee-video-setting` 后端（FastAPI）。

**现象**：`dev` 容器里登录 `operator` A 密码通过、2FA 验证也过，但发 token 时 500：`jwt.exceptions.InvalidKeyError: HMAC key must not be empty.`；登录 admin 直接 401（TOTP 比对失败）。

## 根因

**根因**：`docker-compose.dev.yml` 的 `env_file: ../.env` 字段**不等于 bind mount**——它只在容器 CREATE 时把 `../.env` 文本里的 `KEY=VALUE` 灌入 `os.environ`。如果该容器是早期创建时（`.env` 中尚无 `FLYSEE_AUTH_ACCESS_SECRET` / `FLYSEE_AUTH_REFRESH_SECRET` / `FLYSEE_AUTH_MASTER_KEY`），后补的 KEY 因容器 create-time 快照而被**遗漏**。`pydantic-settings` 命中 `SettingsConfigDict.env_prefix="FLYSEE_AUTH_"` 在 environ 上 → 三个字段全空串 → `AuthSettings` 三个 str 默认 `""` 通过校验（validator 仅在非空时才检查） → `MySQLAuthProvider._encode` 拿 `access_secret=""` 传 `jwt.encode` → 抛 InvalidKeyError。admin 的 TOTP 密文是用某次 master key 加密的，后端用另一个 master key 解密 → TOTP 永远不匹配 → 401。

## 解决方案

**解决**：
- dev 容器加显式 bind mount（`- ../.env:/app/.env:ro`），让 pydantic-settings 走 `env_file=".env"` 全量加载 + 容器运行时与 `.env` 字节级一致；
- 仅改 `.env` 值后需 `docker compose up -d`（重建容器）才把新 env 灌入进程，`docker restart` 不会重读 `env_file`；
- 验证：`docker exec <app> sh -c 'cat /app/.env'` 与 `.env` 对得上、`python -c 'from backend.core.config import s; print(s.auth.access_secret[:4], s.auth.master_key)'` 输出非空；
- 不要在 `AuthSettings` 给 `access_secret / refresh_secret / master_key` 设非空默认值（让空值在启动期就被配置规范抓出来）。生产应由 `.env` 明确要求强随机值。

## 验证

原文「解决」段：`docker exec <app> sh -c 'cat /app/.env'` 与 `.env` 对得上、`python -c 'from backend.core.config import s; print(s.auth.access_secret[:4], s.auth.master_key)'` 输出非空。

## 适用边界与反例

**附带坑**：`docker exec` 拿到的 `printenv` 只能看到 create 时的 env；改 `.env` 文件后 `docker exec ... printenv` 看不到新品种 —— 这是 compose 行为，不是 bug。

## 参考

- 源记录: `docs/known-pitfalls/backend/鉴权与会话.md`
