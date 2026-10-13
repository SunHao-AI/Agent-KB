---
id: kb-20261012-961c
title: Seed SQL 在 latin1 客户端连接下执行会把中文二次编码
type: pitfall
domain:
- database
tags:
- mysql
- encoding
- utf8mb4
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-01'
updated: '2026-10-12'
related:
- kb-20261012-367e
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/database/编码与字符集.md
---

# Seed SQL 在 latin1 客户端连接下执行会把中文二次编码

## 背景 / 现象

前端首页/菜单显示 `ç³»ç»Ÿç®¡ç†å‘˜`、`é¦–é¡µ` 等 mojibake; 后端 `/auth/profile` 原始 JSON 也返回同样的乱码。

## 根因

表结构虽是 `utf8mb4`, 但 seed SQL 在 `character_set_client=latin1` 的 mysql 客户端会话中执行。UTF-8 SQL 文件里的中文被客户端按 latin1 解释, 再被 MySQL 转成 UTF-8 入库, 形成"双重 UTF-8 编码"。`HEX(column)` 可见 `C3A7C2B3...` 这类二次编码字节。

## 解决方案

1. 所有含中文的 seed SQL 文件顶部必须写 `SET NAMES utf8mb4;`, 手动执行时也应加 `mysql --default-character-set=utf8mb4 ...`。
2. 存量 mojibake 可用 DML 反向修复:

```sql
UPDATE ... SET col=CONVERT(CAST(CONVERT(col USING latin1) AS BINARY) USING utf8mb4) WHERE HEX(col) LIKE 'C3%';
```

执行前先 `SELECT` 抽样确认还原结果。

## 验证

排查"前端乱码"时先看后端原始响应与数据库 `HEX`, 不要只改前端编码; 修复后 `HEX(column)` 不再出现 `C3%` 类二次编码字节。

## 适用边界与反例

反向修复 DML 仅适用于"UTF-8 被按 latin1 双重编码"这一种 mojibake(特征 `HEX` 以 `C3` 等 latin1→UTF-8 映射字节开头); 其他编码链路损坏(如 GBK 转码)不适用该公式。若 SQL 根本执行中断/截断, 属传输层问题, 见 powershell-pipe-encoding-truncation 条目。

## 参考

- 源记录: `docs/known-pitfalls/database/编码与字符集.md` (git 首次收录 2026-09-01)
