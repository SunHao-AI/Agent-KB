---
id: kb-20261012-4cb5
title: 令牌换密钥不能一刀切：header.kid + 多公钥并存
type: pitfall
domain:
- backend
tags:
- keyring
- key-rotation
- kid
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-03'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/密钥与授权轮换.md
---

# 令牌换密钥不能一刀切：header.kid + 多公钥并存

## 背景 / 现象

<!-- 待补: 原始记录未含背景/现象(原文以根因开篇) -->

## 根因

**根因**：v1 授权体系下签名密钥是单文件（`license_private.pem` / `license_public.pem`），一旦轮换密钥，全网已分发的客户端 token 立即全部验签失败——除非同时重新导出全部算法包，等于"换密钥 = 全网断服"。验签侧（algorithm 引擎、Phase 2 客户端）也只持有单公钥，无任何过渡语义。

## 解决方案

**方案**：引入 `backend/crypto/license_keyring.py` 多 kid 密钥环：

- 密钥按 kid 落盘：`{LICENSE_KEY_DIR}/license_private_{kid}.pem` / `license_public_{kid}.pem`，kid 形如 `k2609`；`current_kid` 指针文件标记当前签发密钥。轮换 = 生成新 kid + 切指针，旧公钥文件保留期内继续参与验签。
- token header 增加 `kid` 与 `version`：`{"alg":"RS256","typ":"FLYSEE-LICENSE","version":2,"kid":"k2609"}`；验签侧按 `header.kid` 选钥，旧 kid 的 token 在保留期内照常通过（轮换不断服）。
- 旧版单文件密钥以保留 kid `k0000` 迁移，v1 无 kid 的旧 token 兜底按 kid 升序取最新 / `k0000` 处理。
- `.zcfg` 下发字段同步从 `server_public_key`（单 PEM）改为 `server_public_keys`（`{kid: PEM}` 映射），验签侧（Phase 2）必须同步适配。

## 验证

原文「要点」指认实测踩点：`get_license_public_keys()` 缺 ensure 语义时全新部署首次导出前下发空映射，activate 通道客户端无钥可验（Phase 1 Task 6 实测踩过）。

## 适用边界与反例

**要点**：

- **删除旧公钥文件即立即废掉对应 token**——kid 保留期与清理策略要先于轮换动作明确；`all_public_keys()` 只包含磁盘上现存的公钥。
- `get_license_public_keys()` 这类"取公钥"函数必须保留**隐式 ensure 生成**语义（先 `ensure_keypair()` 再枚举），否则全新部署在首次导出前会下发空映射，activate 通道客户端无钥可验（Phase 1 Task 6 实测踩过）。
- 测试隔离密钥目录用 monkeypatch `settings.LICENSE_KEY_DIR` 指向 tmp_path；注意"缺省路径首次生成即落 current_kid 指针"，否则 `current_kid()` 会漂移。

## 参考

- 源记录: `docs/known-pitfalls/backend/密钥与授权轮换.md`
