---
id: kb-20261012-95bb
title: 4 个日志级别名（`INFO/WARNING/SUCCESS/ERROR`）方块宽度不一——PS/Bash 模板必须显式 `PadRight(7)`
  / `%-7s`
type: pitfall
domain:
- frontend
tags:
- logging
- alignment
- script
scope: universal
status: accepted
severity: medium
confidence: verified
created: '2026-09-18'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/构建工具与开发流程.md
---

# 4 个日志级别名（`INFO/WARNING/SUCCESS/ERROR`）方块宽度不一——PS/Bash 模板必须显式 `PadRight(7)` / `%-7s`

## 背景 / 现象

> 面向：`flysee-video-setting` / `flysee_video_web` 两个仓库的 `scripts/dev.ps1` / `scripts/dev.sh` / `scripts/dev-all.ps1` / `scripts/dev-all.sh` 共 **6 个 dev 脚本的 `Write-Log`（ps1）/ `log()`（sh）日志函数**。本条是 **2 仓横切**的 developer-tooling 守护，凡是手写"时间插槽 = 消息插 = 级别"的终端/容器日志行（含 loguru 模板、自实现 pretty printer 等），都按同一规则排查。

（2026-09-13，`flysee_video_web/scripts/dev.ps1` 启动日志）：

```
[2026-09-13 11:16:07] [Success]welcome to ...
[2026-09-13 11:16:07] [Info   ]frontend running...
[2026-09-13 11:16:07] [Warning]file X not found, falling back...
[2026-09-13 11:16:07] [Error  ]up -d failed: ...
```

裸插值的 `[$level]` 让 4 个级别名（`SUCCESS` 7 / `ERROR` 5 / `WARNING` 7 / `INFO` 4）的方块宽度不一致——阅读长日志时眼睛要反复横跳"这条是 warning 还是 info"。

## 根因

- PS `Write-Host "[$level] ..."` 与 Bash `printf "[%s] ..."` 默认裸插值，不补宽。
- AGENTS.md「CJK 双宽对齐」原本管 CJK 字符，但**同级原则**同样适用于"等宽 ASCII 但长度不一的级别列"：4 个级别名最长为 7，必须按 7 列对齐。
- 仓库目前有 `.ps1` BOM 守护、有 pre-commit 钩子拦 BOM 缺失，但**没有**"终端日志格式"守护，新写一个 hand-rolled logger 默认就是裸插值。

## 解决方案

1. **PS（5.1 与 pwsh 7 通吃）**：

   ```powershell
   function Write-Log {
     param([string]$Level, [string]$Message)
     $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
     #4 个级别名（SUCCESS/ERROR/WARNING/INFO）最长 7 字符，左对齐补到 7 列；
     #与 Bash 的 printf '%-7s' 行为一致；合规于 AGENTS.md「CJK 双宽对齐」
     #（此处级别列纯 ASCII，PadRight 按字符宽度计算正确，无需 CJK 双宽修正）。
     $padded = $Level.PadRight(7)
     $colors = @{ SUCCESS='Green'; ERROR='Red'; WARNING='Yellow'; INFO='Cyan' }
     Write-Host "[$timestamp] [$padded] $Message" -ForegroundColor $colors[$Level]
   }
   ```

2. **Bash（POSIX 兼容）**：

   ```bash
   log() {
     local level="$1"; shift
     local color
     case "$level" in
       SUCCESS) color='\033[32m' ;;
       ERROR)   color='\033[31m' ;;
       WARNING) color='\033[33m' ;;
       *)       color='\033[36m' ;;
     esac
     #4 个级别名（SUCCESS/ERROR/WARNING/INFO）最长 7 字符，左对齐补到 7 列；
     #合规于 AGENTS.md「CJK 双宽对齐」：级别列纯 ASCII，%-7s 按字符宽度正确。
     #消息体若含 CJK，本函数不对其再做二次对齐（终端宽度对齐由外层 display_width 负责）。
     printf "${color}[$(date '+%Y-%m-%d %H:%M:%S')] [%-7s] %s${RESET}\n" "$level" "$*"
   }
   ```

3. **`-Success` / `-Error` / `-Warning` / `-Info` 四个别名函数**（PS 端写 `Success/Warning/...: ...` 的袖珍 helper）也要各自 `PadRight(7)`，否则 alias 与主 `Write-Log` 长度漂移。

## 验证

（2026-09-13 落地后 6 脚本全跑，同一行不同级别消息首列对齐）：

```
[2026-09-13 13:05:13] [INFO   ] 消息 1 - container up
[2026-09-13 13:05:13] [WARNING] 消息 2 - listening on fallback port
[2026-09-13 13:05:13] [SUCCESS] 消息 3 - port mapping healthy
[2026-09-13 13:05:13] [ERROR  ] 消息 4 - compose up failed
```

3 个 `.sh`（`web/dev.sh` / `web/dev-all.sh` / `setting/dev.sh`）实跑 4 级别同列；3 个 `.ps1`（`web/dev.ps1` / `web/dev-all.ps1` / `setting/dev.ps1`）`Write-Log` 函数体 Read 比对一致。

## 适用边界与反例

- 这条是**纯 ASCII 等宽列**对齐（级别名长度不一），用 `PadRight(7)` / `%-7s` 即可；
- AGENTS.md 原文的 `display_width`/`pad_width` 必须**仍然**用在**消息体可能含 CJK** 的场景（日志正文、表格列、KV 行），不要拿这条反过来给 CJK 列单独写 `PadRight`（按字符数算 CJK 会少 1 列错位）；
- 写 fresh logger 时的检查顺序：**先看列里会不会混 CJK**——会混用 `display_width/pad_width`，不会混再退回 `PadRight`/`%-7s` 这种轻量补宽。

- PR / review 新增 dev 脚本时 checklist 必查项：`Write-Log` 是否对 `$Level` 做 `PadRight(7)`；`log()` 是否对 `$level` 用 `%-7s`。**裸 `[$level]` 即 reject**。
- 把本规则写进 AGENTS.md「代码风格 → CLI/终端与日志输出对齐」段，作为与「CJK 双宽对齐」并列的子规则。
- 自定义 pretty printer（loguru sink、Click echo 表格封装、彩色 dumper）新增时，抽函数体单测确认 4 级别消息同列对齐再合入。
- `dev-all.ps1` T01-T04 新增服务 / dev-all 新增 compose 服务名时，**别改 log 模板的级别列宽度**（4 级别集已固定，新增级别要么 4 选 1，要么整列 `PadRight` 该扩到 7 重算一次）。

- BOM 钩子管**文件编码与字符解码**（字节层），Write-Log 格式管**终端显示列宽**（字符渲染层），两个钩子是不同维度的 dev-tooling 守护。
- 修 BOM 时**不要顺手改 `Write-Log` 函数体**（例如把 `[$level]` 挪字符串旁边当"顺手优化"），会丢失本条约定；改 `Write-Log` 时也**不要顺手去 BOM**（BOM 钩子会拦）。两个钩子/约定正交维护，互不污染。

## 参考

- 源记录: `docs/known-pitfalls/frontend/构建工具与开发流程.md`
