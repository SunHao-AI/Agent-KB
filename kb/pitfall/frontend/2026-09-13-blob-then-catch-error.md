---
id: kb-20261013-11b4
title: blob 错误处理链 `.then(...).catch(...)` 自 catch 自：业务文案弹完后兜底分支再弹一次，调用方还被塞回被替换的 error
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-13'
updated: '2026-10-13'
severity: medium
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/请求错误提示与BizError.md
---

# blob 错误处理链 `.then(...).catch(...)` 自 catch 自：业务文案弹完后兜底分支再弹一次，调用方还被塞回被替换的 error

## 背景 / 现象

下载类接口（日志导出/报表 blob）失败时后端返回 JSON/文本错误体，用户看到**两条 toast 先后弹出**：先是解析出的业务文案（如「日志日期范围无效」），紧接着又弹一条兜底文案（`Request failed with status code 400` 原文）；且调用方 `catch` 拿到的不是业务 Error 而是被兜底分支换掉的原始 axios error。附带口径缺陷：错误体是 FastAPI `{detail: "..."}` 时 blob 分支只取 `.msg` 取不到，业务文案根本没解析出来（非 blob 分支早已 detail 优先）。

## 根因

1. **Promise 链上 `.then` 里 `return Promise.reject(...)` 会被尾随 `.catch` 捕获**——本意"只兜 `text()` 读取失败"的 catch 实际兜住了 fulfilled 路径的业务 reject（自 catch 自）。`try { throw } catch` 的同款陷阱在 Promise 链上失去 try/catch 的视觉边界，审查时极易看漏。

2. blob 分支是后补的旁路，没跟主分支对齐 detail/msg 口径（同文件 155-159 行 detail 优先，blob 分支只认 msg）。

3. 既有测试只覆盖「blob 成功透传」，失败路径（blob 错误体）零覆盖。

## 解决方案

改两参 `.then(onFulfilled, onRejected)`：onRejected 只兜 `text()` 本身失败（ fulfilled 侧的业务 reject 不再回灌）；解析口径对齐主分支 `body.detail || body.msg`。新增 3 用例（JSON msg / 纯文本 / JSON detail，均断言 `ElMessage` 恰好一次 + reject 的是业务 Error）红→绿；前端全量 **198 passed（17 files）**。

## 验证

新增 3 用例（JSON msg / 纯文本 / JSON detail，均断言 `ElMessage` 恰好一次 + reject 的是业务 Error）红→绿；前端全量 **198 passed（17 files）**。

## 适用边界

- **`.then(...).catch(...)` 里如果 then 自己会 reject，尾随 catch 必然吞掉它**：需要"catch 只兜前半段异步失败"时一律写两参 `.then(onOk, onErr)`；写 `.then().catch()` 前先问"then 有没有可能 reject，那个 reject 该不该进这个 catch"。

- 抓拍图 objectURL 生命周期健康：`imageUrlCache` 并发去重 + `onUnmounted` 统一 `revokeObjectURL`，元素换绑竞态有 `__imageKey` 防护。

- `settings/index.vue` 日志下载 `click()` 后同步 `revokeObjectURL` 在 Chrome/Edge/Firefox 均安全（下载在 click 同步时刻已启动）。

- `plugins/download.js` 为若依模板死代码（`/common/download` 路由后端不存在、`$download.name/zip` 全仓零调用；`proxy.download` 走的是 request.js 版且唯一使用方 ExcelImportDialog 未被引用）——不构成缺陷，待清理项。

## 参考

- 源记录: `docs/known-pitfalls/frontend/请求错误提示与BizError.md` 「blob 错误处理链 `.then(...).catch(...)` 自 catch 自：业务文案弹完后兜底分支再弹一次，调用方还被塞回被替换的 error」
