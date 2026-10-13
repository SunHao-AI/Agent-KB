---
id: kb-20261012-8a17
title: gitignore 不代表没进过历史：.env.prod.bak 曾入库，移出工作目录 ≠ 抹除
type: pitfall
domain:
- backend
tags:
- git
- secret
- history
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-10-11'
updated: '2026-10-13'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/密钥与授权轮换.md
---

# gitignore 不代表没进过历史：.env.prod.bak 曾入库，移出工作目录 ≠ 抹除

## 背景 / 现象

> 面向：用 gitignore"保护"含密钥备份文件的任何仓（本例：本仓 `.env.prod.bak`，2026-10-11 终审发现）。

**现象**：`.env.prod.bak` 自始被 `.gitignore` 覆盖（`.env*.bak`），工作区核查以为"从未入库"；`git log --all -- .env.prod.bak` 实锤 `4270b2b` 曾把 17 行内容完整提交，`13e22b3` 才删除——任何有仓库读权限的人 `git show 4270b2b:.env.prod.bak` 可还原全部 prod 密钥。

## 根因

`.gitignore` 只作用于尚未跟踪的路径, 对已入库的 blob 无任何追溯效力; 该文件在 ignore 规则生效前(或经绕过)曾被完整提交, 而 git 历史是不可变的对象库, 后续删除提交只移除其后的工作树形态, 早期 blob 仍可按 `git show <commit>:<path>` 还原, 故泄露判定必须基于全历史而非当前状态.

## 解决方案

<!-- 待补: 原始记录未含解决方案 -->

## 验证

原文实证：`git log --all -- .env.prod.bak` 实锤 `4270b2b` 曾把 17 行内容完整提交，`13e22b3` 才删除——`git show 4270b2b:.env.prod.bak` 可还原全部 prod 密钥。

## 适用边界与反例

**要点**：
- 处置密钥泄露备份文件必须**三查**：工作区（删除/移出）、当前索引（`git ls-files`）、全历史（`git log --all --stat -- <file>`）。
- 历史已暴露时，实质缓解只有**轮换该密钥**（本项目 `flysee_secret_key1` 已入三仓黑名单强制拒绝）；改写历史（filter-repo/BFG）仅在仓库对外泄露或读权限面失控时考虑，代价 = 全员强推。
- 同类陷阱：`git rm --cached` 后文件"消失"于 `git status`，历史 blob 仍在。泄露判定永远基于历史而非 HEAD。

## 参考

- 源记录: `docs/known-pitfalls/backend/密钥与授权轮换.md`
