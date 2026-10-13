---
id: kb-20261012-7359
title: 页签切换白色矩形闪烁：route.name 与组件 name 不一致导致 keep-alive 失效
type: pitfall
domain:
- frontend
tags:
- keep-alive
- router
- loading-mask
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-01'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/登录鉴权与keep-alive.md
---

# 页签切换白色矩形闪烁：route.name 与组件 name 不一致导致 keep-alive 失效

## 背景 / 现象

TagsView 页签间切换（如"规则"/"算法库"）时，内容区先出现一个短暂的白色矩形（el-table 的 v-loading 遮罩），随后才恢复正常显示。

## 根因

动态路由 `buildRoutes`（store/modules/permission.js）用后端菜单中文显示名做 `route.name`（如"规则"），而 `<keep-alive :include="cachedViews">` 的 include 按 **SFC 组件 name**（如 `Algorithms`）匹配。tagsView.cachedViews 收集的是 route.name，两者永不匹配 → 缓存永不命中 → 每次切页签组件完整卸载重挂载 → `onMounted` 重新拉数据 → `v-loading` 白色遮罩（`el-loading-mask`）闪现。`fade-transform` 的 `mode="out-in"` + `transition: all .5s` 把"空白→白遮罩→内容"全过程进一步放大给用户。

## 解决方案

1. permission.js 中维护 `COMPONENT_NAME_MAP`（组件路径 → SFC name），叶子视图路由的 `route.name` 取映射值，保证 route.name === 组件 name，keep-alive 才能命中缓存。
2. `fade-transform` 过渡属性由 `transition: all` 收窄为 `transition: opacity, transform`，减少过渡期间的重绘范围。
3. **新增业务视图时**：SFC 用 `<script setup name="Xxx">` 声明组件名后，必须同步登记到 `COMPONENT_NAME_MAP`，否则该页 keep-alive 静默失效，切页签重复请求并闪 loading 遮罩。排查"页签切换闪白/重复请求"时，先比对 route.name 与组件 name 是否一致。
4. keep-alive 生效后的预期行为变化：切回页签展示缓存数据而非重新拉取；需要强制刷新时用 TagsView 右键/按钮的"刷新页面"（`$tab.refreshPage` 会 delCachedView 后走 /redirect 重挂载）。
5. **后续补充（2026-08-30）**：keep-alive 修复后仍有用户反馈"刷新后首次切页签闪白遮罩"——这是 keep-alive 无法覆盖的场景（硬刷新后缓存为空，每个页签首次进入必然重挂载拉数据）。根因是 `el-loading-mask` 默认背景 `rgba(255,255,255,.9)` 盖在浅灰内容区上形成白色矩形。解决：`element-ui.scss` 全局加 `.el-loading-mask { background-color: transparent; }`（不加 `!important`，`ElLoading.service` inline style 显式指定的背景不受影响），遮罩透明化仅保留加载图标。**keep-alive 解决"重复出现"，遮罩透明化解决"首次出现"，两者需同时做。**

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

<!-- 待补: 原始记录未含边界说明 -->

## 参考

- 源记录: `docs/known-pitfalls/frontend/登录鉴权与keep-alive.md`
