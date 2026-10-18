---
id: kb-20261012-82bb
title: qrcode 库在浏览器端 API 是 `QRCode.toDataURL`，不是 `new QRCode`
type: pitfall
domain:
- frontend
tags:
- qrcode
- library-api
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
review_by: '2026-11-01'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/登录鉴权与keep-alive.md
---

# qrcode 库在浏览器端 API 是 `QRCode.toDataURL`，不是 `new QRCode`

## 背景 / 现象

两台浏览器 console 都报 `Uncaught (in promise) TypeError: qr.toDataURL is not a function`，生成的 2FA 二维码区域空白。

## 根因

`npm i qrcode` 是 CommonJS 命名导出（`module.exports = { create, toDataURL, toCanvas, ... }`），Vite 在浏览器端通过 ESM interop 包装后，`import QRCode from 'qrcode'` 得到的是命名空间对象（含 `default` 与直接导出双份），`QRCode.toDataURL(...)` 直接可用——plan 文档写的 `import QRCode from 'qrcode'` 正确。误走错路径（`new QRCode(el, text)`）是混淆了 `qrcodejs`（另一热门但废弃的旧库、面向 DOM 挂载）。

## 解决方案

Vite + `qrcode` 库统一用 `QRCode.toDataURL(text, { width, margin })` 异步函数式 API，返回 `Promise<string>`；若需挂到 `<img src>` 直接 `await` 赋给 ref 即可。**别再混淆 `qrcode` 与 `qrcodejs`；按 `package.json` 实际安装的库名查对应 README**。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/登录鉴权与keep-alive.md` :: 「qrcode 库在浏览器端 API 是 `QRCode.toDataURL`，不是 `new QRCode`」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例



源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/登录鉴权与keep-alive.md` :: 「qrcode 库在浏览器端 API 是 `QRCode.toDataURL`，不是 `new QRCode`」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/登录鉴权与keep-alive.md`
