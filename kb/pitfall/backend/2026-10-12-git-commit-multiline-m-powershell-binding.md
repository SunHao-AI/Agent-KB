---
id: kb-20261012-1796
title: git commit 多行 `-m` 消息在 PowerShell 报 "The command parameter was already specified"
type: pitfall
domain:
- backend
tags:
- git
- powershell
- commit-message
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-05'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/测试与开发环境.md
---

# git commit 多行 `-m` 消息在 PowerShell 报 "The command parameter was already specified"

## 背景 / 现象

> 面向：所有仓库的 Windows 宿主提交流程。

**现象**：`git commit -m "多行消息…"`（消息含换行、引号、`{}` 等大括号）经 PowerShell 执行报 `ParameterBindingException: The command parameter was already specified`，commit 未发生；同批用 `;` 链接的 `git push` 反而先执行并输出 `Everything up-to-date`，容易造成"已提交"错觉。

## 根因

**根因**：Trae/agent 终端把命令写入 `.ps1` 执行，长多行带特殊字符的 `-m` 字符串在 PowerShell 参数绑定阶段被拆成多个位置参数，触发该异常；这是 shell 层解析问题而非 git 问题。

## 解决方案

**解决**：多行提交信息一律先 `Write` 临时 `_commit_msg.txt`，再 `git commit -F _commit_msg.txt`，提交后删除临时文件。单行短消息才允许 `-m`。

## 验证

原文实录: 报 `ParameterBindingException: The command parameter was already specified`, commit 未发生而同批 `git push` 反先输出 `Everything up-to-date`; 规避为 `-F _commit_msg.txt` + commit 后 `git log --oneline -1` 确认 hash 变化再 push。

## 适用边界与反例

**防踩**：agent 自动提交场景固定走 `-F` 文件方案；`git commit` 后必须 `git log --oneline -1` 确认 hash 变化再 push。

## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
