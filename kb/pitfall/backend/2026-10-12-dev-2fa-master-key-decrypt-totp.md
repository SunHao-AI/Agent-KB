---
id: kb-20261012-140a
title: dev 环境攻克 2FA 登录：backend 容器内用 master key 解密 TOTP secret + pyotp 现算动态码（2026-09-29）
type: pitfall
domain:
- backend
tags:
- 2fa
- totp
- dev-smoke
- master-key
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-10-01'
updated: '2026-10-13'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/测试与开发环境.md
---

# dev 环境攻克 2FA 登录：backend 容器内用 master key 解密 TOTP secret + pyotp 现算动态码（2026-09-29）

## 背景 / 现象

> 面向：`flysee-video-setting` dev/冒烟场景下 admin 已强制开启 2FA、但手头没有验证器 App，`POST /v1/auth/login/2fa` 恒 401 的自救。**前提：仅对自己拥有授权的开发环境使用**（背景与"用户拿不到 secret"的产品缺陷分析见 `鉴权与会话.md`「admin 强制开启 2FA 但用户拿不到 TOTP secret → 恒 401」条目，本条是其 dev 侧实操补全）。

**场景**：登录链为 `POST /v1/auth/login`（username/password，无图形码）→ 返回 `pending_2fa` → `POST /v1/auth/login/2fa`（`{username, code}`）→ accessToken/refreshToken。dev 库的 admin `totp_enabled=1` 而无人持有验证器 → 第二因子无法提供。

## 根因

2FA 校验的本质是后端用库内 totp_secret 按 TOTP 算法算码比对, 验证器 App 只是持有 secret 的一种载体而非唯一算码方; secret 以 master key 可逆加密存库, 意味着在 backend 容器内用同一把 key 与同一组参数即可等价重算出同一无损动态码, 故 dev 无验证器也能自救.

## 解决方案

**原理**：TOTP secret 以 AES-GCM 密文存 `fs_uav_auth.sys_user.totp_secret`（HKDF 域 `flysee:store:totp`），后端校验即 `pyotp.TOTP(secret, digits=6, interval=30).verify(code, valid_window=1)`。因此**在 backend 容器内用应用自身的 master key 解密同一 secret 并现算**，与验证器 App 完全等价——零新增代码，复用应用解密链。

**实操（已验证单行命令，输出即 6 位动态码）**：

```powershell
docker exec flysee-video-setting-backend python -c "import pyotp;from backend.core.config import settings as s;from backend.core.database import AuthSessionLocal as A;from backend.auth.provider.models import SysUser as U;from backend.crypto.master_key import DOMAIN_TOTP as D,decrypt_store as X;db=A();u=db.query(U).filter(U.username=='admin').first();print(pyotp.TOTP(X(s.auth.master_key or s.master_key,D,u.totp_secret).decode(),digits=6,interval=30).now())"
```

输出码 30s 有效（`valid_window=1` 容忍 ±30s），直接投 `POST /v1/auth/login/2fa` 或填入登录 UI 的 6 格验证码输入即可换发 token。

## 验证

原文标注「已验证单行命令」: docker exec backend 内用应用自身 master key 解密 + pyotp 现算, 输出即 6 位动态码(30s 有效), 直接投 `POST /v1/auth/login/2fa` 换发 token。

## 适用边界与反例

**要点**：
- master key 取值**必须与后端同优先级链** `settings.auth.master_key or settings.master_key`——用错另一把 key 会 `InvalidTag`（见 `鉴权与会话.md`「双 master key 导致 AES-GCM InvalidTag」）。
- **解出的明文 secret 严禁落盘/进文档/进日志**：上述命令现算现打印动态码，秘密不出容器。脚本化冒烟时把命令输出直接管道给下一步，不要 `> secret.txt`。
- 动态码是瞬时值，冒烟脚本里**登录与填码要连续执行**，别复用上一轮打印的码（30s 后 401）。
- 浏览器自动化填 6 格 `TwoFactorInput`：组件是 `@input` 驱动，用原生 value setter + `input` 事件逐格填入即可；**勿派发合成 `blur`**（Element Plus 会报 `Invalid event arguments: event validation failed for event "blur"`）。

## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
