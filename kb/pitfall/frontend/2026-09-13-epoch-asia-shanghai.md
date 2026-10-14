---
id: kb-20261013-27e3
title: 秒级 epoch 渲染成日历日必须固定 Asia/Shanghai，否则非 +08 浏览器差一天
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
confidence: probable
created: '2026-09-13'
updated: '2026-10-13'
severity: medium
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/时间与时区展示.md
---

# 秒级 epoch 渲染成日历日必须固定 Asia/Shanghai，否则非 +08 浏览器差一天

## 背景 / 现象

后端 `license_expires_at` 是秒级 epoch（绝对时刻）。前端用「本地时区 getter」把它渲染成到期日历日：

```js

const d = new Date(expiresAt * 1000)

const text = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

```

`2027-08-15T00:00:00+08:00` 这个到期时刻，在 UTC 时区的浏览器/测试环境下会渲染成 `2027-08-14`——**差一天**。测试也因此对运行环境的 `TZ` 敏感（`TZ=UTC` 跑 spec 直接红）。

## 根因

`getFullYear/getMonth/getDate` 按运行环境本地时区取分量。AGENTS.md 的 workspace-wide 铁律要求所有展示墙钟统一 `Asia/Shanghai`，而浏览器时区不受部署控制——用户在海外打开后台，看到的到期日就会漂一天。这与后端/容器的时区铁律是同一问题的前端侧。

## 解决方案

上海无夏令时，固定 `+08:00` 偏移即精确等价于 `Asia/Shanghai`，比 `Intl.DateTimeFormat` 少 API 面且测试天然 TZ 免疫：

```js

// 固定 +08:00 偏移取日历日（上海无夏令时，偏移恒定）

const sh = new Date(expiresAt * 1000 + 8 * 3600000)

const text = `${sh.getUTCFullYear()}-${pad(sh.getUTCMonth() + 1)}-${pad(sh.getUTCDate())}`

```

要点：

- 加偏移后用 **UTC getter**（`getUTCFullYear` 等），把「已偏移到上海墙钟」的时刻按 UTC 读，得到正确的上海日历日。

- `daysRemaining` / `expired` 是**绝对时刻差**，与时区无关，不要跟着改。

- 加一条 TZ 免疫测试并保留：`$env:TZ='UTC'; npm run test` 必须仍全绿——这就是本修复的回归护栏。

## 验证

凡「后端给 epoch / 绝对时刻，前端要落成日历日期字符串」的地方，一律走固定 +08:00 偏移或 `Intl.DateTimeFormat(..., {timeZone:'Asia/Shanghai'})`，禁止裸用 `getFullYear` 等本地时区 getter。后端已格式化成 `YYYY-MM-DD HH:mm:ss` 字符串的字段（如 `installed_at`）前端直接展示，不二次解析。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/时间与时区展示.md` 「秒级 epoch 渲染成日历日必须固定 Asia/Shanghai，否则非 +08 浏览器差一天」
