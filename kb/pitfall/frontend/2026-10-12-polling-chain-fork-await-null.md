---
id: kb-20261012-6305
title: 轮询链自我分裂：`await` 期间定时器为 null 使外部触发另起新链（导出进度轮询 2s → N×2s）
type: pitfall
domain:
- frontend
tags:
- polling
- set-timeout
- race-condition
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-12'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/登录鉴权与keep-alive.md
---

# 轮询链自我分裂：`await` 期间定时器为 null 使外部触发另起新链（导出进度轮询 2s → N×2s）

## 背景 / 现象

导出列表存在 `packing` 行时，`GET /v1/exports` 的请求频率会随用户操作次数成倍增长且永不自愈；后端日志里同一 URL 的访问密度越来越高，页面挂一整天后能刷出上千次请求。

## 根因

`schedulePolling()` 原实现是"自我续命"式递归，且回调内部自己发请求：

```js
pollTimer = setTimeout(async () => {
  pollTimer = null            // ← 危险窗口开始
  await getExportList(...)    // 期间 pollTimer === null
  schedulePolling()           // ← await 回来后无条件再排一次
}, 2000)
```

`await` 期间 `pollTimer` 已是 `null`，此时任何外部调用 `schedulePolling()`（`fetchList` 收尾、keep-alive 的 `onActivated`、`el-pagination` 的 size-change 双触发）都会走进 `stopPolling(); pollTimer = setTimeout(...)` —— `clearTimeout(null)` 什么都没撤销，于是新建了**第二条链**；而第一条链 `await` 回来后还会再排一次。N 条链各自 2s 一轮，且链数只增不减。

## 解决方案

把"发请求"从轮询回调里拿出来，回调只负责排期，请求统一走 `fetchList`，用三道闸收敛成单链：

```js
let inflightKey = null   // 同条件在途去重
let listSeq = 0          // 过期响应作废

function schedulePolling() {
  stopPolling()          // 进入即撤销：定时器永远只有一个槽位
  if (!tableData.value.some((r) => r.status === 'packing')) return
  pollTimer = setTimeout(() => {
    pollTimer = null
    fetchList({ silent: true })
  }, POLL_INTERVAL)
}

async function fetchList({ silent = false } = {}) {
  const query = { page: currentPage.value, page_size: pageSize.value, keyword: keyword.value.trim() || undefined }
  const queryKey = JSON.stringify(query)
  if (silent && inflightKey === queryKey) return   // 同条件在途 → 复用那次请求
  stopPolling()
  const seq = ++listSeq
  inflightKey = queryKey
  if (!silent) loading.value = true
  try {
    const res = await getExportList(query)
    if (seq !== listSeq) return                    // 已被更新的请求取代 → 丢弃
    tableData.value = res?.items || []
  } finally {
    if (inflightKey === queryKey) inflightKey = null
    if (seq === listSeq) loading.value = false     // 条件必须与置 true 时一致
  }
  schedulePolling()                                // 轮询链唯一出口（成功/失败都续上）
}
```

## 验证

用后端访问日志在固定窗口计数，比浏览器 Network 面板可靠（`browser_network_requests` 无时间戳，且 `performance.getEntriesByType('resource')` 缓冲区默认 250 条满后静默丢弃新条目）：

```powershell
docker logs flysee-video-setting-backend --since <字面量 UTC 时间戳> 2>&1 |
  Select-String "GET /v1/exports" | Measure-Object | Select-Object -ExpandProperty Count
```

制造 `packing` 行最快的办法是纯 DML 插一条合成记录（`status='packing'`），比真跑 50MB 打包快几个数量级；测完记得删。**注意 `--since` 需传字面量时间戳，PowerShell 变量传参可能失效导致退化成全量计数。**

## 适用边界与反例

1. **`setTimeout` 回调里若有 `await`，则 `pollTimer` 在 await 期间必然是 `null`** —— 任何"先判 null 再新建"的定时器管理在此窗口都会失效。要么让回调保持同步（本方案），要么改用独立的 `running` 标志位。
2. **`clearTimeout(null)` 是静默空操作**，不能指望它撤销别人的链；必须先 `stopPolling()` 再排期，让"一个槽位"成为不变量。
3. **遮罩开关条件必须前后一致**：置 `true` 用 `!silent`、置 `false` 用 `seq === listSeq` 会留下永久卡住的 loading —— 静默轮询抢先返回时把 `listSeq` 抬高，用户那条请求回来被判过期而跳过清理。两处都该用 `seq === listSeq`。
4. **keep-alive 页的 `onActivated` 里只调 `schedulePolling()` 是安全的**（收敛后它等价于"重新排期"），但若轮询回调自带请求，`onActivated` 就是最典型的分裂触发源。

## 参考

- 源记录: `docs/known-pitfalls/frontend/登录鉴权与keep-alive.md`
