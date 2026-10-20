---
id: kb-20261020-9676
title: Register-ScheduledTask 的 AtLogOn 触发器不带 -User 在非管理员令牌下被策略拒绝
type: pitfall
domain:
- devops
tags:
- scheduled-task
- powershell
- autostart
- privilege
scope: project
status: accepted
confidence: verified
created: '2026-10-20'
updated: '2026-10-20'
severity: medium
verification:
  evidence: '本机非管理员 PowerShell 二分实验(2026-10-20): AtLogOn 无-User 拒/有-User 通; schtasks.exe
    全拦; kb serve --install-autostart 实跑成功, Get-ScheduledTask=Running, /api/health
    ok, 幂等重装通过'
  reviewed_at: '2026-10-20'
---

# Register-ScheduledTask 的 AtLogOn 触发器不带 -User 在非管理员令牌下被策略拒绝

## 背景 / 现象

实现 `kb serve --install-autostart`（Windows 登录自启动）时，普通权限 PowerShell 里注册计划任务连续被拒（`Access is denied`, HRESULT 0x80070005），但同一终端里"最简任务"却能注册成功。二分实验（同一终端、同一用户令牌）：

| 注册方式 | 结果 |
| --- | --- |
| `schtasks /create`（任何形态，含最简 ONLOGON） | ❌ Access denied（受管终端策略整体拦截） |
| `Register-ScheduledTask -Action`（无触发器） | ✅ |
| `Register-ScheduledTask -Action -Settings`（电池/时限/重启策略） | ✅ |
| `Register-ScheduledTask -Action -Trigger (New-ScheduledTaskTrigger -AtLogOn)` | ❌ Access denied |
| `-AtLogOn -User $env:USERNAME`（显式绑定当前用户） | ✅ |

## 根因

`New-ScheduledTaskTrigger -AtLogOn` **不带 `-User` 时语义是"任意用户登录"**——这是系统级任务，写任务计划程序根目录需要提升令牌；带 `-User` 才是"该用户登录"的用户级任务，普通令牌可写。报错是 CimException `PermissionDenied`，容易被误读为"整个 cmdlet 都需要管理员"，与 schtasks.exe 被组策略整体拦截的表象混在一起，掩盖了真正的最小差异。

另：`Register-ScheduledTask -Xml`（自定义 XML 含 `<Principal>`）在本机同样被拒 0x80070005，而 cmdlet 原生参数（-Action/-Trigger/-Settings）可通——受管环境对 XML 直注 principal 更严格，优先用原生参数拼装。

## 解决方案

普通权限下注册登录自启任务的最小可行组合（`src/kb/autostart.py` 采用）：

```powershell
$a  = New-ScheduledTaskAction -Execute $cmd -Argument $args -WorkingDirectory $wd
$t  = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME   # -User 必须有
$si = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
      -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName kb-serve -Action $a -Trigger $t -Settings $si -Force
```

要点：`-Force` 覆盖实现幂等重装；`-ExecutionTimeLimit Zero` = 不限时长（常驻服务必需，默认 72h 会被杀）；优先 cmdlet 原生参数而非 `-Xml`。

## 验证

本机实测（2026-10-20，非管理员 PowerShell）：`kb serve --install-autostart` 输出"已注册并启动"；`Get-ScheduledTask -TaskName kb-serve` 状态 `Running`；`Invoke-WebRequest http://127.0.0.1:4320/api/health` 返回 `{"ok": true, "schema": 2}`；重复执行安装命令幂等成功。

⚠ 验证常驻服务时先查端口占用（`Get-NetTCPConnection -LocalPort 4320 -State Listen`）：遗留的同端口旧进程会让 health 检查"假通过"（本次即旧会话 serve 占着 4320，health 返回的是旧进程的 traces_dir）。

## 适用边界与反例

- 适用于：普通用户令牌 + 未禁用 Task Scheduler cmdlet 的 Windows；受管终端若连 `Register-ScheduledTask` 全被拦，退路是启动文件夹放 `.lnk`/VBS 或申请管理员一次性注册。
- 反例：需要"任何用户登录都启动"（如机器级守护）时绕不开 `-User` 缺失的管理员语义，此时必须提权，本方案不适用。
- systemd 用户级 unit（`systemctl --user enable --now`）无此坑，Linux 侧直接可用。

## 参考

- 实现: 本仓 `src/kb/autostart.py`（install_windows 注释含二分结论）
- 关联任务: docs/plans/2026-10-20-observability-b1-b4-followups.md A-2
