---
id: kb-20261012-19d3
title: CSV 导出中文乱码 — 必须前端加 BOM 前缀
type: pitfall
domain:
- frontend
tags:
- csv
- export
- encoding
- bom
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-01'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/上传与文件处理.md
---

# CSV 导出中文乱码 — 必须前端加 BOM 前缀

## 背景 / 现象

`views/system/operlog/index.vue` 导出操作日志 CSV，下载后用 Excel 打开，表头/操作人/用户名列全变问号/乱码。

## 根因

`responseType: 'blob'` 返回的应用的后端 `text/csv` 字节流可能是 UTF-8 无 BOM，Excel 在按单字节编码判定时把 UTF-8 多字节中文字符识别为 `?` 或乱码（Excel 2016+ 虽支持 UTF-8 但依赖 BOM）。

## 解决方案

`handleExportOper` 里拼 `new Blob(['\ufeff', blob])`，强制 U+FEFF（BOM）；下载 `a.download = '操作日志_YYYYMMDD.csv'`。凡"经浏览器下载的二进制/文本资源"（日志、报表、导出任务），前端拼 BOM 是最后一道防线——后端生产环境无法控制 Excel 默认编码。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/上传与文件处理.md` :: 「CSV 导出中文乱码 — 必须前端加 BOM 前缀」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例



源记录无边界/反例记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/上传与文件处理.md` :: 「CSV 导出中文乱码 — 必须前端加 BOM 前缀」）。上述结论适用范围以「根因」与「解决方案」段所载机制为限；换项目/版本使用前先在最小场景验证机制成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/上传与文件处理.md`
