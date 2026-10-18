---
id: kb-20261012-dff8
title: 导出文件名前后端两份拼接规则漂移
type: pitfall
domain:
- frontend
tags:
- filename
- cross-platform-contract
- unit-test
scope: universal
status: accepted
severity: medium
confidence: probable
created: '2026-09-12'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/应用包闭环形态.md
---

# 导出文件名前后端两份拼接规则漂移

## 背景 / 现象

`.zapk` 下载文件名（`{cid}_{version}.zapk`，版本为空时为 `{cid}.zapk`）最初在 **后端** `backend/services/export_service.py` 拼一次（落盘名）+ **前端** `views/exports/index.vue` 内再拼一次（浏览器 `Blob.name`），两处拼接规则**对用户可见字符串必须一致**——但版本名为空时是否带 `_` 分隔符在两份代码里没写进单测锁定，规则一旦漂移（如某次重构成不同 prefix/suffix 形态）前端落盘名与后端 zip 内 manifest 解不一致，用户解压时看到文件名漂移。

## 根因

文件名是规则拼接产物（`{client_id}_{version_slug}{ext}`），跨端"两份代码各拼一次"是典型的薄层复制。规则本身简单，但**空值分支**（version 缺省时是否含 `_`）属于用户可见字符串的可校验行为点，必须锁单测。

## 解决方案

1. 抽纯函数 `zapkFilename(row)`（`src/views/exports/export-display.js`），入参是后端返回的 `row`（含 `client_id`、`version`、`version_label` 等），按其约定拼出落盘名；
2. 加 `__tests__/export-display.spec.js` 含三用例：版本非空拼 `_{version}.zapk`；版本为空只取 `client_id` 不带 `_`；版本字段全空 `version: null` 时拼出 `client_id.zapk`；
3. `views/exports/index.vue` 的 `handleDownload` 改用 `zapkFilename(row)`，不再模板侧重拼；
4. 后端 `export_service.py` 的落盘名**保持为 zip 内部唯一事实来源**，前端 `Blob` 名仅用于浏览器下载弹框展示，**与 zip 内 `manifest.json` 的 `package_name` 一致**。

## 验证



源记录无验证记载（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/应用包闭环形态.md` :: 「导出文件名前后端两份拼接规则漂移」：原文仅现象/根因/解决，无验证步骤或命令输出）。采信前由使用者按「根因/解决方案」段自行复现验证。

## 适用边界与反例

（2026-09-10 用户拍板）：`zapkFilename` 产物**必须与后端 `export_service.py:193-196` 落盘名逐字一致**（整包会下发，不能漂）；`zdiffFilename` 的 `.zdiff` **浏览器保存名由前端自定**（后端 `exports.py:213-220` 的下载接口是 `StreamingResponse` 且不带 `Content-Disposition`，磁盘名 `diff_{cid}_{from_ver}_{to_ver}.zdiff` 从不下发给用户），可保留 `v` 前缀可读形式（如 `diff_7_v2_v3.zdiff`）。

跨端拼接用户可见字符串（文件名、URL slug、文案模板）必须抽纯函数 + 单测锁分支。尤其**含 "空值省略" 语义**的规则（空版本不带 `_`、空 client 名不上 `_`），仅靠代码 review 不锁规则。

## 参考

- 源记录: `docs/known-pitfalls/frontend/应用包闭环形态.md`
