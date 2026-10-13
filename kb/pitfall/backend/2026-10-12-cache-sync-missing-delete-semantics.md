---
id: kb-20261012-f321
title: 捎带下发的缓存快照缺「清除语义」：服务端清空策略后客户端永吃过期值
type: pitfall
domain:
- backend
tags:
- cache-sync
- contract
- absent-field
scope: universal
status: accepted
severity: high
confidence: verified
created: '2026-09-23'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/性能与容错优化.md
---

# 捎带下发的缓存快照缺「清除语义」：服务端清空策略后客户端永吃过期值

## 背景 / 现象

> 面向：方案 B quota 策略下发链 setting→renew→web→Redis→engine（`flysee_video_web` `license_sync_service.sync_now`, 2026-09-23 E2E-T4 暴露）。

**现象**（E2E-T4）：管理页给客户配 `quota_gpu_free_mb=1500` 后 engine 阈值正确变 1500；把该值**清空**（DB 置 NULL）后再同步，renew 应答确实不再带 `quota_token` 键，但 engine 侧 `effective_client_config` 仍是 1500——「清空策略」不生效，最长滞留 7 天（快照 exp）。

## 根因

**根因**：搬运逻辑只写了正向路径「应答带 quota_token → 验签 → SET」，漏掉反向路径「应答**不带**该键 → 服务端已无策略 → **DEL** 旧快照」。`data.get("quota_token") or ""` 为空时静默跳过，Redis 里的旧 token 原封不动。单测也只覆盖了「带键缓存/不带键跳过」，"跳过"当时被当成正确语义写进了断言——**契约里"缺省 = 无值"和"缺省 = 维持现状"是两种语义, 缓存型搬运必须是前者**。

## 解决方案

**解决**（web `sync_now` renew 成功分支）：
```python
quota_raw = str(data.get("quota_token") or "")
if quota_raw:
    if store_quota_token(config, quota_raw):
        result["quota_cached"] = True
else:
    try:
        get_redis().delete(QUOTA_CACHE_KEY)
    except Exception as exc:  # Redis 故障下旧快照靠 TTL/engine exp 自然失效
        logger.warning("quota 快照清除失败（已忽略）：{}", exc)
```
关键边界：**只有 renew 成功**（拿到带业务码应答）才判定"无策略"并清除——网络不可达 / ServerError 分支绝不能 DEL（setting 宕机时误清 = 把 fail-open 容灾打没, 与"容忍宕机 7 天"的设计直接冲突）。单测 `test_sync_clears_quota_when_server_omits_token`（FakeRedis 补 `delete` 记录）锁死。

## 验证

原文实录: E2E-T4 暴露(清空 DB 值后 engine 侧 `effective_client_config` 仍 1500); 单测 `test_sync_clears_quota_when_server_omits_token`(FakeRedis 补 delete 记录)锁死删除语义。

## 适用边界与反例

**通用教训**：
- **"服务端省略字段 = 无配置"的捎带契约, 消费端缓存必须实现删除语义**：SET-only 的搬运工在配置被删除后永远播放旧值, 且过期时间越长越隐蔽（本例 7 天）。设计缓存同步时把「新增/更新/**删除**」三态写进契约表再编码。
- **区分"应答缺键"与"没有应答"**：前者是权威状态（删）, 后者是未知状态（不动）。两者都走 `get(...) or 默认值` 就会混淆——必须在"应答成功"分支内处理缺键。
- 验证删除语义的 E2E 套路：配置→生效→**清空→必须回落**, 三步缺一就漏掉这类 bug（本次 T1-T3 全过, 只有 T4 清空步骤暴露）。

## 参考

- 源记录: `docs/known-pitfalls/backend/性能与容错优化.md`
