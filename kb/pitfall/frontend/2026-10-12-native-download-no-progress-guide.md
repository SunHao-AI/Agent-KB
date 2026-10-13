---
id: kb-20261012-263c
title: 原生 `<a href>` 下载「看不到进度」—— 浏览器不暴露下载字节数，只能用引导弹窗兜
type: pitfall
domain:
- frontend
tags:
- download
- ux
- browser
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-12'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/上传与文件处理.md
---

# 原生 `<a href>` 下载「看不到进度」—— 浏览器不暴露下载字节数，只能用引导弹窗兜

## 背景 / 现象

切到原生 `<a href>` 流式下载后，点「打包下载」立即弹保存框（比旧 blob 快很多，符合预期），但**页面内没有任何进度反馈**，用户不知道下了多少、还要等多久。

## 根因

原生下载一旦交给浏览器下载管理器，**JS 拿不到实时字节数**：
- `fetch` + `ReadableStream` 能读 chunk 计数，但**要自己负责落盘**（攒内存或写 File System Access / IndexedDB）→ 又回到「大文件攒内存」的老炸弹，且 100GB 仍需手动分块。
- XHR `onprogress` 同样要 JS 全权消费响应体，绕开浏览器下载管理器，`responseType` 不是 blob 也躲不开「JS 搬运」语义。
- 结论：**「让浏览器原生流式落盘（省内存 + Range 续传）」与「页面内实时进度」二者不可兼得**。

## 解决方案

新增 [components/DownloadProgressGuide.vue](file:///d:/WorkPlace/Pycharm/flysee-video-setting/frontend/src/views/exports/components/DownloadProgressGuide.vue)，点下载后弹**一次性引导对话框**，把用户真正需要的信息一次给全：
- 总大小（HEAD 探测，见下）+ 是否续传（`content-range` 已收偏移）
- **进度入口指引**：`Ctrl+J` 打开浏览器下载页 / 窗口底部下载条（保存框是 OS 层窗口，会盖住 Chrome 底部下载条——这才是用户「看不到进度」的直接原因）
- 带 ticket 的**直链**（10min 内可复制去 `curl -C -` 手动续传）
- footer 串到部署指引，避免原生下载切走后「下载完下一步做什么」丢失
- `sessionStorage` 记「不再提示」；静音后降级为 `ElMessage` 进度 toast，**绝不静默**（保住 spec「下载后自动引导」）

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

签票后对 download 端点做一次 `HEAD`（[probeDownloadMeta(url)](file:///d:/WorkPlace/Pycharm/flysee-video-setting/frontend/src/api/exports.js)）：`content-length` = 总大小；`content-range: bytes 0-N/total` = 续传时已收偏移。`FileResponse` 对 HEAD 不读盘，代价仅一次握手。probe 失败用 `row.file_size` / `diffResult.total_size` 兜底。

（都因「改造时只动一半」）：
1. `const silenced = ref(() => {…})()` —— `ref` 包了个函数，`.value` 恒为函数（truthy），`showDlGuide` 的 `if (silenced.value) return` 永真 → **弹窗永不出现**。改为 `ref(readSilenced())` 存布尔值。
2. 进度弹窗的静音路径若直接 `return`，会连带**部署指引抽屉**也不再自动弹（spec §3.4 回归）。`showDlGuide` 必须**返回布尔**：true=已弹引导（其 footer 再串部署抽屉），false=已静音，调用方须自己兜底 `openGuide` / 进度 toast。

- 文件下载 UX 决策先问：**要不要 JS 处理字节**？不要 → 原生 `<a href>`，接受「无页面内进度」，用引导弹窗 + `Ctrl+J` 提示补体验；要 → 才有进度，但自担流式落盘与内存。
- 用「引导弹窗承载一次性提示」替代 `ElMessage` 刷屏时，弹窗**必须返回是否真弹**，让每条静音路径都有降级出口，别把同函数里的其它副作用（如开部署抽屉）一起 return 掉。
- `ref(fn)` 是高频手滑：`ref` 存**值**，需要惰性求值就 `computed(fn)` 或初始化时 `ref(fn())`，别 `ref(fn)` 后又当布尔用。

## 参考

- 源记录: `docs/known-pitfalls/frontend/上传与文件处理.md`
