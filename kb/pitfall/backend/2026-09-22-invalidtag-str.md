---
id: kb-20261013-5bd3
title: 异常消息为空串（`InvalidTag`）：只打 `str(e)` 得到的是零信息日志
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-22'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: low
source:
  project: flysee_video_algorithm
  ref: docs/known-pitfalls/backend/日志统一与故障表达.md
---

# 异常消息为空串（`InvalidTag`）：只打 `str(e)` 得到的是零信息日志

## 背景 / 现象

`ERROR | app.services.detect_service:_start_yolov:340 - 模型加载失败:`
——冒号后什么都没有，任务报"模型加载失败"但完全无法定位。

## 根因

`logger.error(f"模型加载失败: {e}")` 只取 `str(e)`。而 `cryptography` 的

`cryptography.exceptions.InvalidTag` **消息就是空串**（`repr(e)` 才是 `InvalidTag()`），

AES-GCM tag 校验失败恰好抛的就是它 → 唯一线索被丢掉。本例实测（容器内直接调

`ModelLoader._decrypt_enc`）：

```

head256_all_zero= False     # 不是 v3 租约路径（该路径会带明确 RuntimeError 文案）

EXC cryptography.exceptions.InvalidTag repr= InvalidTag() str= ''

```

即 RSA 信封解开、AES-GCM 校验不过 → **该 `.enc` 与当前 `.env` 里的 RSA 私钥不是同一套密钥**

（或文件损坏），属"任务必然起不来"的确定性故障。

## 解决方案

错误日志统一带异常类型 + traceback，已知类型追加可操作提示：

```python

except Exception as e:

    err_type = type(e).__name__

    hint = "（AES-GCM tag 校验不通过：模型文件与当前 RSA 私钥不匹配，或文件已损坏）" if err_type == "InvalidTag" else ""

    logger.opt(exception=True).error(f"模型加载失败: {err_type}: {str(e) or '<空消息>'}{hint}")

```

## 验证

本例实测（容器内直接调 `ModelLoader._decrypt_enc`）：

```
head256_all_zero= False     # 不是 v3 租约路径（该路径会带明确 RuntimeError 文案）
EXC cryptography.exceptions.InvalidTag repr= InvalidTag() str= ''
```

即 RSA 信封解开、AES-GCM 校验不过 → **该 `.enc` 与当前 `.env` 里的 RSA 私钥不是同一套密钥**（或文件损坏），属"任务必然起不来"的确定性故障。

## 适用边界

`except` 里禁止只打 `f"...: {e}"`——第三方异常可能消息为空（`InvalidTag`、

部分 `KeyError()`、C 扩展异常），必须带上 `type(e).__name__` 且用 `logger.opt(exception=True)` /

`logger.exception` 留堆栈；"空消息"本身也显式打出来，提示读者消息缺失而非日志被截断。

## 参考

- 源记录: `docs/known-pitfalls/backend/日志统一与故障表达.md` 「异常消息为空串（`InvalidTag`）：只打 `str(e)` 得到的是零信息日志」
