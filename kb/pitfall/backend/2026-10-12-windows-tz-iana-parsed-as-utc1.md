---
id: kb-20261012-96d0
title: TZ=Asia/Shanghai 在 Windows 被当 UTC+1（宿主机禁止注入 TZ）
type: pitfall
domain:
- backend
tags:
- timezone
- windows
- tzset
- iana
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-04'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/时区与容器.md
---

# TZ=Asia/Shanghai 在 Windows 被当 UTC+1（宿主机禁止注入 TZ）

## 背景 / 现象

> 面向：`flysee-video-setting` / `flysee_video_algorithm` 宿主机（Windows PowerShell + CPython）。

**现象**：在宿主机 `dev.ps1` / `python -c "import os; os.environ['TZ']='Asia/Shanghai'; import time; time.tzset()"` 后，`datetime.now().astimezone().strftime('%z')` 输出 `+0100`，当时应为上海 `+0800`；Python 把 IANA 名 `Asia/Shanghai` 当字面 UTC+1 处理。

## 根因

**根因**：glibc / node / OpenSSL 等在 Linux 下读 IANA zoneinfo，但 **Windows CPython 的 `time.tzset()` 实现不支持 IANA 名**（见 Python docs：tzset 只在 Unix-like 平台生效，Windows 下忽略）。应用代码里 `os.environ['TZ'] = 'Asia/Shanghai'` 在 Windows 工厂无效；而某些子系统（PyQt / pytz）反而会把 IANA 名当**短期名**（UTC+1 / +12:10:35 这种 offset 解析），得到错误 UTC+1。

## 解决方案

**解决**：工作区统一**与 Windows 无关**的时区策略 = 只用 `Asia/Shanghai` 字符串做**声明性** across compose `TZ` 与 `.env` `APP_TIMEZONE`，但**任何宿主机启动脚本/进程都禁止把 APP_TIMEZONE 当作 `TZ` 环境变量注入**；宿主机让系统时区（OS 控制面板 / `Get-TimeZone`）决定墙钟，应用层裸 `datetime.now()` 跟随系统时区即可。compose 只会把 `${APP_TIMEZONE:-Asia/Shanghai}` 作为容器 environment 的 `TZ`，不进宿主机。

## 验证

原文「铁证」段(本机对照实验, 上海 13:38 时做测试): `TZ=UTC` → 05:38; `TZ=Asia/Shanghai` → 06:38(被当 UTC+1 而非 +08:00); `TZ unset`(系统默认上海)→ 13:38。

**铁证**（本机对照实验，上海 13:38 时做测试）：
- `TZ=UTC` → 05:38
- `TZ=Asia/Shanghai` → 06:38（与 tz 未注入时相差 1h = 被当 UTC+1 而非 +08:00）
- `TZ unset`（系统默认上海）→ 13:38

三项对照证明 IANA 名在 Windows CPython 下**不是按 Linux 走 Shanghai**，而是走了某个**UTC+1 偏移**读法，所以代码侧绝不能用 IANA 名交换 `TZ`。

## 适用边界与反例

**预防**：
- 当篇幅要在宿主机日志/CLI 加时区标注时，优先用 `datetime.now().astimezone().strftime('%z')` 直接读系统原生 offset，而非依赖 `os.environ['TZ']`；
- 若业务必须固定时区，用 `zoneinfo.ZoneInfo('Asia/Shanghai')` + `datetime.now(tz)` 得到 **aware** 时间，不要 setenv `TZ`；
- algorithm 端的 `startup_timezone()`（`app/config.py`）只读 `APP_TIMEZONE` 做启动自检日志，不参与换算，避免引入"内嵌 IANA 名交换 TZ"反模式。

## 参考

- 源记录: `docs/known-pitfalls/backend/时区与容器.md`
