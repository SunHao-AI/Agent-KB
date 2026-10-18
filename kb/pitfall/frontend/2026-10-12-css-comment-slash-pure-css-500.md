---
id: kb-20261012-3093
title: 纯 CSS 的 `<style scoped>` 里写 `//` 注释 → Vite 500 + 路由白屏
type: pitfall
domain:
- frontend
tags:
- css
- postcss
- vite
- vue-sfc
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-12'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/构建工具与开发流程.md
---

# 纯 CSS 的 `<style scoped>` 里写 `//` 注释 → Vite 500 + 路由白屏

## 背景 / 现象

（2026-09-11，`views/exports/index.vue`）：

- 容器 `flysee-video-setting-frontend` 日志刷 `[plugin:vite:vue] Unexpected '/'. Escaping special characters with \ may help.`，栈底是 `Parser.combinator` → `LazyResult.runAsync`（postcss-selector-parser）
- 该模块 HTTP 请求返回 **500 Internal Server Error**（容器日志 `Internal server error`）
- 浏览器 6 条日志：`net::ERR_ABORTED ...index.vue?vue&type=style&index=0&scoped=xxx&lang.css` + `TypeError: Failed to fetch dynamically imported module` + Vue Router `uncaught error during route navigation`，页面白屏
- 误导点：报错行号指向 `.vue` 的 **template 段**（如 `index.vue:70:1`），实际出错位置在文件尾部的 `<style>` 段。postcss 的行号是**相对 style 块内容**的偏移，compiler-sfc 未把行号映射回 SFC 绝对行

## 根因

`<style scoped>`（**没有 `lang="scss"`**）是**纯 CSS**，`//` 不是合法 CSS 注释。`// 下载中按钮的状态文案…` 被 postcss 当成选择器解析，`Parser.combinator` 读到 `/` 直接抛 `Unexpected '/'`。

同一文件里 `<script setup>` 段合法使用 `//` 注释，容易产生"这个文件支持 `//`"的错觉——**SFC 各 block 的语言是独立声明的**。

## 解决方案

把 `//` 改成 `/* ... */`。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/构建工具与开发流程.md` :: 「纯 CSS 的 `<style scoped>` 里写 `//` 注释 → Vite 500 + 路由白屏」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例

- 加 CSS 注释前先看 `<style>` 标签有没有 `lang="scss"`（或 `lang="sass"`/`less`）；**没有就一律用 `/* */`**
- 本仓库多数 `.vue` 的 `<style scoped>` 是纯 CSS，默认按纯 CSS 写
- 判断这类白屏的快速分诊：`ERR_ABORTED` + `Failed to fetch dynamically imported module` + 容器 `Internal server error` → 先怀疑 **SFC 编译失败**，而非网络/权限问题；用 `Invoke-WebRequest` 直接请求 `/src/<组件>.vue` 看状态码（200 = 编译通过，500 = 编译失败），比在浏览器里反复刷新快得多

## 参考

- 源记录: `docs/known-pitfalls/frontend/构建工具与开发流程.md`
