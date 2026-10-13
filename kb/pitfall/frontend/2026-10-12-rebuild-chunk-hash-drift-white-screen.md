---
id: kb-20261012-40c8
title: 重建前端镜像后旧页面点进未缓存路由白屏：`net::ERR_ABORTED .../static/js/index-<旧hash>.js`（2026-09-24
  web）
type: pitfall
domain:
- frontend
tags:
- pwa
- chunk
- service-worker
- self-healing
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-25'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/构建工具与开发流程.md
---

# 重建前端镜像后旧页面点进未缓存路由白屏：`net::ERR_ABORTED .../static/js/index-<旧hash>.js`（2026-09-24 web）

## 背景 / 现象

进入「创建分析任务」这类**懒加载路由**的 `div` 标签页时，控制台报 `net::ERR_ABORTED https://127.0.0.1:15443/static/js/index-Co9IqSGa.js`，调用栈停在动态 import（`qo`/`component` 帧），页面白屏。**后端/nginx 完全正常**：`/health` 与 `/` 均 200，nginx 无 `emerg`。

## 根因

**浏览器缓存的 SPA 版本 与 服务端产物版本错位**。`build:prod` 用 contenthash 命名 chunk，每次重建镜像全量 hash 变更。取证三件套即可定性：
1. 容器内 `ls static/js | grep <报错hash>` → 该 chunk **与它的入口 chunk 双双不存在**；
2. 当前 `index.html` 引用的入口是**另一个** hash（新入口 `curl` 200，报错旧 chunk `curl` 404）；
3. `index.html`/`sw.js` 缓存头本就是 `no-cache`（服务端无过错）。

链路：标签页在**重建之前**就打开 → 内存里仍是旧版 SPA → 点进未预缓存的懒加载路由 → 按**旧路由映射**动态 import 旧 contenthash chunk → 已被新构建替换 → nginx 404 → 动态 import 被拒, Chrome 报成 `net::ERR_ABORTED`。与同文件「jszip 未装」「SFC 编译失败」两条同样是 `ERR_ABORTED + Failed to fetch dynamically imported module` 表象, **但根因是发版/重建后的版本漂移, 不是依赖/编译问题**——判定关键: 报错 chunk 在容器里 404 且入口 chunk hash 对不上 `index.html`。

## 解决方案

（不改码即可恢复）：硬刷新 `Ctrl+Shift+R`（旧 SPA 的 chunk 引用随新 `index.html` 消失）；若旧 SW 仍干扰 → DevTools Application 里 Unregister SW + Clear site data 再刷。

项目 PWA 走 `registerType:'prompt'`（更新交用户点提示, spec §4.4）→ 旧页面不会自动拿到新 chunk, 缺"chunk 失效自愈"。在 `flysee_video_web/frontend/src/permission.js` 补**全局兜底**：
- `beforeEach` 记录 `pendingTarget = to.fullPath`（失败回调拿不到目标路由, 导航已被打断, 须自己存意图目标）；
- 监听 **Vite 官方 `vite:preloadError`**（预加载/动态 import 失败统一派发, `preventDefault()` 抑制 unhandled rejection）+ `router.onError`（须先 `isChunkLoadFailure(err)` 判定确为 chunk 失效, 否则普通导航错误会被误触发 reload）；
- 命中即**带一次性 sessionStorage 防循环标记**整页重载到 `pendingTarget`（深层路由直连 nginx 拿新 `index.html`）；导航 `afterEach` 成功即清除标记, 保证下次发版仍能自愈一次；重载后同目标仍失败（断网等非发版场景）则不再二次 reload。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

`vite/pwa.js` 里 `navigateFallback: null`（SPA 回退交 nginx, SW 不劫持导航）+ `index.html` 的 NetworkFirst runtimeCaching 只匹配 `pathname === '/'`。因此自愈跳到**深层路由**（`/tasks/create`）不命中 SW 缓存规则, 直连源站拿新 `index.html`。若这两条被改动（启用 `navigateFallback` 或扩大 `index.html` 匹配）, 自愈会被 SW 挡回旧 `index.html` → 失效。

`ERR_ABORTED 某 static/js/index-<hash>.js` + 页面是懒加载路由白屏 → 先 `docker exec 前端容器 ls static/js | grep <hash>` 与 `grep index.html` 对 hash：容器 404 且对不上 = 版本漂移(刷新生效/需自愈兜底), 容器 500/文件在 = 编译/依赖问题(查构建日志)。

## 参考

- 源记录: `docs/known-pitfalls/frontend/构建工具与开发流程.md`
