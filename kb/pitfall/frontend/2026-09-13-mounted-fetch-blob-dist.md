---
id: kb-20261013-f8dd
title: 抓拍图墙 mounted 即全量 fetch blob：71 张图占满浏览器 6 连接拖垮整页——视口懒加载 + dist 冻结镜像复验
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

# 抓拍图墙 mounted 即全量 fetch blob：71 张图占满浏览器 6 连接拖垮整页——视口懒加载 + dist 冻结镜像复验

## 背景 / 现象

浏览器走查任务详情页（71 张抓拍图）：Resource Timing 显示图片平均 ~1s/张、总耗时数秒，页面整体转圈时间长；但同期后端 middleware `duration` 仅 11~14ms——慢不在后端。

## 根因

1. `vLazyImage` 指令名叫 lazy，实际 `mounted` 即对**全部** 71 个元素并发 `fetch blob`。浏览器对同域 HTTP/1.1 只有 **6 个连接位**，71 个大图 fetch 把队列塞满，同页的 getInfo / license-state / SSE 等小请求全部排队——**图片墙拖垮的是整页，不只是图片**。

2. 归因陷阱：先怀疑后端 FileResponse / 挂载卷 IO，容器内实测 stat+read 仅 11.3ms；后以"应用内计时 11-14ms vs 浏览器侧 ~1s/张 + 71 并发"定性为**浏览器连接排队**，修复方向才转向前端。

## 解决方案

- 指令改 `IntersectionObserver`（`rootMargin: '200px'` 预加载一屏）：进入视口才 fetch，`unobserve` 保证只拉一次；`updated` 时换 key、清 src、重新 observe；`unmounted` 清理。首屏请求 71→**11 张**，滚动后按需补齐。

## 验证

第二次进同一任务页 71 张全"已加载"但 `transferSize=0`（磁盘缓存命中），会假象"懒加载没生效"；必须用**未访问过的任务**+重建镜像后重测。

15443 跑的是 nginx+dist 冻结镜像（`Dockerfile.prod`），**改前端源码后浏览器实测仍是旧包**，必须先 `docker compose --env-file .env -f docker/docker-compose.yml -f docker/docker-compose.override.yml build frontend` 再 `up -d frontend`；`up -d frontend` 会因 depends_on **连带重启 backend** → 复验 `/health` 200 + `printenv ALGORITHM_UNLOCK_M2M_KEY` 非空（dev override 的 env 未丢）。

## 适用边界

- "图片墙/长列表 + 每图独立鉴权请求"的页面一律视口懒加载；blob 方案本身没错（Bearer 鉴权所需），错在**并发不设闸**。浏览器 6 连接是硬约束，任何"N 张大图并发 fetch"都会外溢成整页卡顿。

- 前端性能问题先用"后端应用内计时 vs 浏览器 Resource Timing"分层：两边差距大 → 传输/排队层，别动后端代码。

- 本仓前端复验的黄金三步：`build frontend` → `up -d frontend`（连带重启 backend）→ 验 health+env → 浏览器**硬刷新**（Ctrl+F5）+ 全新数据复测。跳任何一步都会得出"改了没效果"的错误结论。

## 参考

- 源记录: `docs/known-pitfalls/frontend/请求错误提示与BizError.md` 「抓拍图墙 mounted 即全量 fetch blob：71 张图占满浏览器 6 连接拖垮整页——视口懒加载 + dist 冻结镜像复验」
