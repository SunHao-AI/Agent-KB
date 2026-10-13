---
id: kb-20261012-5910
title: 用 HMAC 生成"对外 ID 令牌"是错的：不可逆所以无法还原主键
type: pitfall
domain:
- backend
tags:
- crypto
- aes-siv
- id-ref
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-03'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/鉴权与会话.md
---

# 用 HMAC 生成"对外 ID 令牌"是错的：不可逆所以无法还原主键

## 背景 / 现象

> 面向：`flysee-video-setting` 后端（FastAPI）；场景是"UI/URL 不暴露自增主键"（AGENTS 规范）。

**现象**：给详情页 URL 做脱敏，第一反应是 `ref = base64url(HMAC_SHA256(secret, id))[:10]`。写完全链路（列表下发 ref → 前端跳转 → 详情接口按 ref 取记录）才发现**服务端拿到 ref 也解不回 id**，接口没法查库。

## 根因

**根因**：HMAC 是单向 MAC，不是加密。需求同时要求两点时二者不可兼得：
- 「不可推导」（不能从 id 算 ref 猜、也不能从 ref 反推 id）
- 「可还原」（服务端要能从 ref 取回主键查库）

## 解决方案

**解决**：用 **AES-SIV（RFC 5297，确定性认证加密）** —— `backend/crypto/id_ref.py`：

```python
from cryptography.hazmat.primitives.ciphers.aead import AESSIV
ct = AESSIV(key).encrypt(str(id).encode(), [kind.encode()])   # 关联数据 = 表命名空间
ref = base64.b32encode(ct).decode().rstrip("=")               # URL 安全、无 padding
pk = int(AESSIV(key).decrypt(base64.b32decode(padded), [kind.encode()]))
```

选它而非 AES-GCM/CBC 的三个理由，缺一不可：
1. **确定性**：同 id 恒定同 ref → URL 可收藏、可分享、前进后退与硬刷新都稳定（GCM 的随机 nonce 会让每次 ref 都变，直接毁掉可分享性）；
2. **自带认证**：密文被改一个字符就解密失败，不会"解出错位但合法的 id"误命中他人记录（裸 AES-CTR/CFB 有这种风险）；
3. **AAD 做命名空间**：`associated_data=[kind]` 让不同表的 ref 互不可用（拿 client 的 ref 打 models 接口必然解密失败 → 404），无需额外查表。

密钥从 `APP_SECRET_KEY` 经 **HKDF 独立 info** 派生（别直接把业务密钥塞给 AESSIV，也别和 JWT/签名复用同一 key）；`AESSIV` 只接受 32/48/64 字节 key。HKDF 有开销，用 `functools.lru_cache(maxsize=1)` 缓存实例。

**配套约束**：
- base32 去 padding 后解码侧要按 `len % 8` 补回；入口统一 `ref.upper()` 容忍手抄大小写；
- 非法 ref（裸主键 / 篡改 / 垃圾 / 跨表）**统一返回与"记录不存在"相同的 404 文案**，否则等价于把"该 id 是否存在"变成了可探测信号；
- 响应体里保留真实 `id` 只给内部交叉引用（本项目算法表的 `model_id`）用，不进 URL、不进 UI；
- 前端局部变量别叫 `ref`（`<script setup>` 里遮蔽 Vue 的 `ref`），用 `modelRef`。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例



## 参考

- 源记录: `docs/known-pitfalls/backend/鉴权与会话.md`
