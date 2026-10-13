---
id: kb-20261012-24c3
title: Windows PowerShell 5.1 读无 BOM 的 `.ps1` 按 ANSI/GBK 解码炸中文弯引号，配 pre-commit 钩子拦截
type: pitfall
domain:
- frontend
tags:
- powershell
- bom
- encoding
- pre-commit
scope: universal
status: accepted
severity: high
confidence: verified
created: '2026-09-12'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/构建工具与开发流程.md
---

# Windows PowerShell 5.1 读无 BOM 的 `.ps1` 按 ANSI/GBK 解码炸中文弯引号，配 pre-commit 钩子拦截

## 背景 / 现象

> 面向：`flysee-video-setting` / `flysee_video_web` / `flysee_video_algorithm` / `flysee_media_server` 四个仓库的 `scripts/*.ps1`（`dev.ps1` / `dev-all.ps1` 等开发者入口）。本条是**横切四仓**的仓库级守护，所有 stash 共存。

在 Windows PowerShell 5.1 下 `.\dev.ps1 -a start` 抛 `"Try 语句缺少 Catch 或 Finally 子句"` / `"字符串缺少终止符"`，对应行包含 `"` 弯引号（U+201C/201D）或 `、`（U+3001）等中文标点。Git for Windows 已配 UTF-8 时，文件实际是 UTF-8 本身合法，但 **PowerShell 5.1 默认按 ANSI（本机是 GBK）** 读无 BOM 的 `.ps1`，UTF-8 下的 `"` 是 3 字节 `E2 80 9D`，被 GBK 误解为 `"` + `\x80` + 尾字节，导致吞噬单个引号，使 try/catch 配对、字符串终止边界全部形状破坏。

## 根因

PowerShell 5.1 不会推断 UTF-8；只有当文件头 3 字节是 `EF BB BF` 时才走 UTF-8 解码路径，否则按 ANSI（"Current Culture"代码页，中文 Windows 通常为 GBK/936）。Windows Terminal / pwsh 7+ 默认 UTF-8 不会触发，但 Windows 自带的 `powershell.exe`（5.1）会。**仓库层不保证用户终端是 pwsh 7**，所以所有入库 `.ps1` 必须带 BOM。PowerShell 本身不区分选 UTF-8 with BOM vs no BOM——对用户而言，BOM 版本在 win 5.1 / pwsh 7 / docker exec 下都合法等价，**加 BOM 零副作用**。

## 解决方案

（写进钩子在拦截时动态生成）：

1. **编辑器**：VSCode 右下 `UTF-8` 改为 `UTF-8 with BOM`（Cmd/Ctrl+Shift+P → "Reconfigure Encoding" → `utf-8bom`），Save。
2. **字节级 CLI 修复**（不动编码，只插 BOM，最重要因为可以远程/批量/无 IDE）：
   ```powershell
   powershell -NoProfile -Command "$p='D:\...\scripts\dev.ps1'; $b=[IO.File]::ReadAllBytes($p); [IO.File]::WriteAllBytes($p,[byte[]](0xEF,0xBB,0xBF)+$b)"
   ```
   Git Bash 下等价：
   ```bash
   printf '\xef\xbb\xbf' > tmp.ps1
   cat orig.ps1 >> tmp.ps1
   mv tmp.ps1 orig.ps1
   git add orig.ps1   # 必须重新 add 让 hook 重检
   ```
3. **临时跳过钩子**：`BOOTSTRAP_PS1_BOM=1 git commit ...`（**不推荐**，提交后在 PowerShell 5.1 上仍炸，只是延后爆时间点）。

- 检测：只要暂存（index 列 = `A`/`M`/`R`）或修改了任何 `.ps1`，用 `head -c 3 | od -An -tx1` 取前 3 字节，跟 `efbbbf` 比较，不等即拦截（exit 1），并打印 1/2/3 修复选项。
- 只拦"已暂存"行——避免未暂存工作区被误拦（用户可能故意先暂存一组、另一组未暂存）。
- 用 `git -c core.quotepath=false status --porcelain` 而非 `git diff --cached --name-only`——后者在 Git for Windows + `core.fscache=true` + git-lfs `filter.lfs.process` 配置齐备的仓库里，会产生**静默空输出**但 `git diff HEAD` 与 `git status --porcelain` 都正常（web 仓内置证，见下方"Windows 兼容性陷阱"）。

四仓共用**完全相同**的 hook 内容（`.git/hooks/pre-commit`，~3KB）。若单仓内容改了，用一条 PowerShell 字节拷贝 + 内容 hash 比对同步（`.git/hooks/` 不被 Git 跟踪，各仓本地一致才等价）：
```powershell
$src = 'D:\WorkPlace\Pycharm\flysee_video_web\.git\hooks\pre-commit'
$repos = @('D:\WorkPlace\Pycharm\flysee-video-setting','D:\WorkPlace\Pycharm\flysee_video_algorithm','D:\WorkPlace\Pycharm\flysee_media_server')
$srcBytes = [System.IO.File]::ReadAllBytes($src)
foreach ($r in $repos) {
  $dst = Join-Path $r '.git\hooks\pre-commit'
  if (Test-Path $dst) {
    $dstBytes = [System.IO.File]::ReadAllBytes($dst)
    if ([System.Linq.Enumerable]::SequenceEqual($srcBytes,$dstBytes)) { continue }
  }
  [System.IO.File]::Copy($src, $dst, $true)
}
```

## 验证

1. 建 `_no_bom_test.ps1`（空文件，无 BOM），`git add`，跑 `.git/hooks/pre-commit` → 期望 exit=1，列出该文件。
2. 建 `_with_bom_test.ps1`（内容 `\xef\xbb\xbf# ok`），`git add`，跑 hook → 期望 exit=0。
3. 两个同时 stage → 期望 exit=1，列表里只列无 BOM 那个。
4. 干净 worktree → exit=0。
5. `BOOTSTRAP_PS1_BOM=1 .git/hooks/pre-commit` → exit=0，打印 SKIPPED 提示。

## 适用边界与反例

钩子只拦 `git commit`，**拦不住"改完直接跑"**。Agent / 脚本用编辑工具（diff 式 SearchReplace、`WriteAllText(..., UTF8Encoding($false))`、`Set-Content`、`Out-File` 等）改写已有 `.ps1` 时会**静默丢掉 BOM**，症状与上文完全一致（`Missing '(' after 'if' in if statement`、`The Try statement is missing its Catch or Finally block`、中文提示显示成乱码）。改 `scripts/*.ps1` 后必须立刻字节校验并按需补回：
```powershell
$p = 'D:\...\scripts\dev.ps1'
$b = [IO.File]::ReadAllBytes($p)
if (($b[0..2] | ForEach-Object { $_.ToString('X2') }) -join ' ') -ne 'EF BB BF' {
  [IO.File]::WriteAllText($p, [IO.File]::ReadAllText($p, [Text.UTF8Encoding]::new($false)), [Text.UTF8Encoding]::new($true))
}
```
同理，`.yml` / `.md` 在本仓是**无 BOM**，不要用同一段代码给它们"统一加 BOM"（会给 `git diff` 制造首行伪改动）——按文件类型分别确认 HEAD 的实际字节，别用 `git show HEAD:<path> > tmp` 判断编码（PowerShell 重定向会自己改写编码，结论不可信；用 `git diff` 首行是否显示 `﻿` 或直接读工作区字节）。

- **`git diff --cached` 静默空输出**：`git status --porcelain` 显示 `A scripts/xxx.ps1`（已暂存新增）、`git ls-files --stage` 能列出对应 blob，但 `git diff --cached --name-only`/`--raw`/`--shortstat` **全部静默返回空，exit code=0**。`git diff HEAD --name-only` 却正常输出同一列表。最小复现（fresh `git init` + `core.autocrlf=true`）下正常，机制未完整解（怀疑 fscache + lfs + 实际 index 校验链交互）。**代入修复**：钩子用 porcelain + diff-HEAD 双保险。
- **`tr '\0' '\n'` 在 Git Bash 不可依赖**：MSYS 的 `tr` 处理 NUL 与 POSIX 标准或有差异。改用 NUL 外的分界符，或直接 bash 逐行 grep。
- **PowerShell 5.1 下 `Set-Content` 不接收 byte array**：用 `[IO.File]::WriteAllBytes` 直写绕开 PSDrive 抽象。

## 参考

- 源记录: `docs/known-pitfalls/frontend/构建工具与开发流程.md`
