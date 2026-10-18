---
id: kb-20261012-a21f
title: 硬刷新后页面切换闪白色矩形：裸 `<script setup>` 未声明 name 导致 keep-alive 全面失效（flysee_video_web）
type: pitfall
domain:
- frontend
tags:
- keep-alive
- script-setup
- loading-mask
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
review_by: '2027-01-16'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/登录鉴权与keep-alive.md
---

# 硬刷新后页面切换闪白色矩形：裸 `<script setup>` 未声明 name 导致 keep-alive 全面失效（flysee_video_web）

## 背景 / 现象

硬刷新（无缓存）后切换页面/页签，内容区先出现短暂白色矩形遮罩，内容渲染完成后才消失，接口慢的页面必现。

## 根因

与「页签切换白色矩形闪烁：route.name 与组件 name 不一致导致 keep-alive 失效」同族但发生在静态路由项目（flysee_video_web）：所有业务视图都是裸 `<script setup>` 未声明组件 name，Vite 按文件名推断 `__name`（四个 `index.vue` 全部推断为 `index`），而 `keep-alive :include="tagsViewStore.cachedViews"` 收集的是 `route.name`（Dashboard/Tasks/...），永不匹配 → keep-alive 缓存命中率为 0 → 每次切换完整重挂载 → `onMounted` 重新拉数据 → `v-loading` 的 `el-loading-mask`（默认 `rgba(255,255,255,.9)`）白色遮罩闪现。`fade-transform` 的 `transition: all .5s` + `mode="out-in"` 进一步放大闪烁。

## 解决方案

1. 项目已配置 `unplugin-vue-setup-extend-plus`（vite/plugins/setup-extend.js），直接给 7 个业务视图写 `<script setup name="Xxx">`，name 与 `router/index.js` 的 `route.name` 严格一致（Dashboard/Suites/SuiteRules/Tasks/CreateTask/TaskDetail/Settings）。**新增业务视图必须同步声明 name 且与 route.name 一致**，否则 keep-alive 静默失效。
2. `transition.scss` 的 `fade-transform` 由 `transition: all .5s` 收窄为 `transition: opacity .3s, transform .3s`，减少过渡期间的重绘范围与时长。
3. 全局消除白色遮罩：`element-ui.scss` 加 `.el-loading-mask { background-color: transparent; }`（不加 `!important`，`ElLoading.service` 通过 inline style 显式指定的背景不受影响），保留加载图标、去掉白色矩形。
4. 验证方法：构建后 `grep 'name:"Dashboard"' dist/static/js` 确认 setup-extend 已把 name 编译进组件选项（KeepAlive 的 `getComponentName` 读 `Component.name`）；`grep 'el-loading-mask{background-color:transparent' dist/static/css` 确认样式入包。

## 验证

（自本条方案段第 4 点提取）构建后 `grep 'name:"Dashboard"' dist/static/js` 确认 setup-extend 已把 name 编译进组件选项（KeepAlive 的 `getComponentName` 读 `Component.name`）；`grep 'el-loading-mask{background-color:transparent' dist/static/css` 确认样式入包。

## 适用边界与反例



源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/登录鉴权与keep-alive.md` :: 「硬刷新后页面切换闪白色矩形：裸 `<script setup>` 未声明 name 导致 keep-alive 全面失效（flysee_video_web）」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/登录鉴权与keep-alive.md`
