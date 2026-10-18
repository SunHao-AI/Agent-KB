---
id: kb-20261012-774b
title: axios `responseType:'blob'` 下载大文件 = 把整包攒进浏览器内存 → 数十 GB 必炸：改「短时签名票据 + 原生 `<a
  href>` 流式下载」
type: pitfall
domain:
- frontend
tags:
- blob
- download
- signed-url
- hmac
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-12'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/上传与文件处理.md
---

# axios `responseType:'blob'` 下载大文件 = 把整包攒进浏览器内存 → 数十 GB 必炸：改「短时签名票据 + 原生 `<a href>` 流式下载」

## 背景 / 现象

点「打包下载」后**很久才弹保存框**（本包 175MB 实测数秒），保存框弹出前无任何进度。用户担忧「加密包 100G（超过服务器内存）会异常」。

瓶颈**不在服务器**。后端 [download_export](file:///d:/WorkPlace/Pycharm/flysee-video-setting/backend/api/v1/exports.py) 用的是 `FileResponse`，实测 starlette 1.3.1 `_handle_simple` 是 `while: chunk = await file.read(chunk_size)`（默认 64KB）**分块流式发送**，服务端内存恒定；且自动带 `accept-ranges: bytes`。实测 `curl -H "Range: bytes=0-15"` → `206 content-range: bytes 0-15/184197592` 直接印证。

## 根因

（旧链路 `axios responseType:'blob'` + `URL.createObjectURL`）：

| 环节 | 175MB | 100GB |
| --- | --- | --- |
| XHR blob 模式 | 攒完整个响应体才 resolve（无 read-progress） | 浏览器需要 ~100GB 内存/临时盘；攒完前保存框根本不出现 |
| `timeout: 300000` | 勉强够 | **5 分钟必 abort**，此前带宽全废 |
| `a.download` 另存 | 双份写盘（Blob + 目标文件） | ~200GB I/O |
| 取消 | 无取消入口，只能刷新页 | 全部重来 |

`responseType:'blob'` 把「浏览器下载管理器」这个本该负责流式落盘 + 进度 + 续传的组件整个绕开了，改成 JS 手工搬运。包越大越接近必然失败。

## 解决方案

让浏览器直接消费 `FileResponse`（浏览器原生下载：进度条 / 可取消 / Range 续传 / 内存恒定）。唯一障碍是原生下载**不能带 `Authorization` 头**，用**短时签名票据**跨过去（S3 presigned URL 模型）：

```
① POST /v1/exports/{id}/download-ticket   (Bearer 鉴权) → {ticket, ttl:600, expires_at}
② <a href="/v1/exports/{id}/download?ticket=...">       → 浏览器流式落盘
```

- 票据实现见 [backend/crypto/download_ticket.py](file:///d:/WorkPlace/Pycharm/flysee-video-setting/backend/crypto/download_ticket.py)：**无状态 HMAC**（HKDF 从 `APP_SECRET_KEY` 派生独立 info `flysee:download-ticket:v1`，与 `id_ref.py` 同模式），形态 `base64url(payload).base64url(HMAC-SHA256)`，payload = `{eid, exp, act}`
- 前端 [api/exports.js](file:///d:/WorkPlace/Pycharm/flysee-video-setting/frontend/src/api/exports.js)：`downloadExport(blob)` 删除，换成 `createDownloadTicket(id)` + `zapkDownloadUrl(id, ticket)`；[handleDownload](file:///d:/WorkPlace/Pycharm/flysee-video-setting/frontend/src/views/exports/index.vue) 改为签票 → `<a download=zapkFilename(row)>` → `a.click()`

1. **票据必须「TTL 内可重复校验」，不能单次使用**。一开始照 `sse.py` 的 SSE ticket 抄成 Redis `GETDEL` 用后即焚，但浏览器下载大文件会用 `Range` 断点续传（暂停/恢复、连接中断都会再发 `Range: bytes=N-`）→ 第二个 Range 请求直接 401，100GB 断一次就废。实测同一张票连打两次：`200` 全量 + `206` Range 均通过。
2. **不用 Redis 而用无状态 HMAC**：setting 仓 `docker/docker-compose*.yml` 里**根本没有 redis 服务**，`REDIS_URL` 派生成不存在的 `redis:6379`（容器内 `getent hosts redis` 返回 2）→ 用 Redis 会直接 500。且这个缺口先于本次改动存在（SSE ticket/stream 在 dev 下同样不可用，只是被前面的 401 挡住了）。无状态签名零基础设施依赖、dev 立即可用。代价是不支持主动吊销与「已用」审计，用短 TTL(600s) + 绑定单个 `export_id` 兜风险。
3. **票据绑定 `export_id`**：拿 A 包的票打下 B 包 → `403 下载票据与目标导出不匹配`（实测）。
4. **票据不落日志**：后端日志只记 `ticket[:8]`；审计中间件 [audit_mw.py](file:///d:/WorkPlace/Pycharm/flysee-video-setting/backend/auth/audit_mw.py) 只记 `request.url.path`（不含 query），且 `user is None`（原生下载无 Bearer）时直接跳过 → 完整票据不会落库。
5. **文件名仍前端单端负责**：同源 `<a download>` 可指定文件名，故 `FileResponse` 继续不传 `filename`，避免前后端两份拼名漂移（`zapkFilename` 仍是唯一来源）。

## 验证

（后端容器内实跑，无 Redis 依赖）：签票原语 `ROUNDTRIP True` / 过期 `ValueError: 下载票据已过期` / 篡改签名 `签名无效` / 空票 / 无分隔符均拒；端到端 `ticket→200 SIZE:184197592`、同票 `Range→206`、跨包 `403`、匿名 `401`。

## 适用边界与反例

- **凡是文件下载，先问「浏览器能不能直接 GET 这个 URL」**。能就别用 axios blob——blob 只适合「拿到后还要在 JS 里处理」（预览、解析、二次上传）
- 原生下载要鉴权 → **query 传短时签名票据**，绝不在 query 传 Bearer/JWT（会进访问日志、Referer、浏览器历史）
- 别照抄别处 ticket 的**单次使用**语义：SSE 建连是一次性动作，下载天生会被 Range 拆成多次请求，两者语义不同
- 用 Redis 前先确认**本仓 compose 真起了 redis**（setting ≠ web 仓，别假设跨仓基础设施同源）
- 密钥派生一律 HKDF + **独立 info 命名域**（`flysee:<用途>:v1`），不与 JWT/id_ref 复用

## 参考

- 源记录: `docs/known-pitfalls/frontend/上传与文件处理.md`
