---
id: kb-20261012-3477
title: Windows PowerShell 不识别 heredoc，python 多行用脚本文件 / `-c` 单行
type: pitfall
domain:
- backend
tags:
- powershell
- heredoc
- shell
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-01'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/测试与开发环境.md
---

# Windows PowerShell 不识别 heredoc，python 多行用脚本文件 / `-c` 单行

## 背景 / 现象

> 面向：`flysee-video-setting` 后端（FastAPI）。

**现象**：`python - <<'PY' ... PY` / `$sql = @" ... "@` 在 PowerShell 直接 `ParserError: MissingFileSpecification / 系统找不到指定的文件`。多条 diikuti 失败。

## 根因

**根因**：PowerShell 不支持 POSIX heredoc；`Get-Content -Raw` 与 `<<` 在上述场景解析位算符。

## 解决方案

**解决**：
- 小段 Python：单条 `-c "..."` 用分号换行（`python -c "import x; y=z; print(y)"`），不需影响语义
- 长片段：写独立 `.py` 临时脚本运行；或 `docker exec` 容器内的 bash 里 heredoc 合法
- PowerShell 内 `@"..."@` here-string 合法（注意前/后行尾不能有多余空格、变量展开开 `${x}` 才有字面值）

## 验证

原文实录: `python - <<'PY'` 与 `$sql = @"..."@` 场景直接 `ParserError: MissingFileSpecification / 系统找不到指定的文件`; 防踩做法为所有 PowerShell 调试片段先用 `-c` 单行验证再展开。

## 适用边界与反例

**防踩**：Windows 环境禁止用 `<<'PY'`；所有涉及 PowerShell 调试片段都先用 `-c` 单行验证再展开。

## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
