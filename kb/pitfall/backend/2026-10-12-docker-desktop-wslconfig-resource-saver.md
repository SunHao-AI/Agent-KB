---
id: kb-20261012-f180
title: Docker Desktop 资源上限的真实来源与 Resource Saver 卡死（WSL2 后端）
type: pitfall
domain:
- backend
tags:
- wslconfig
- resource-saver
- docker-desktop
- sandbox-limits
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-12'
updated: '2026-10-18'
review_by: '2027-04-16'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/测试与开发环境.md
---

# Docker Desktop 资源上限的真实来源与 Resource Saver 卡死（WSL2 后端）

## 背景 / 现象

> 面向：`flysee-video-setting` 本地开发的 Docker Desktop（WSL2 后端）；结论同样适用于另三仓。

### 1. `docker info` 的 CPU/内存上限来自 `.wslconfig`，不是 Docker Desktop

- 实测：`settings-store.json` 里 Docker Desktop 自己的值是 `Cpus: 8, MemoryMiB: 2048`，但 `docker info` 实际是 `CPUs=4 Mem≈4GB`——因为 `C:\Users\<user>\.wslconfig` 的 `[wsl2] memory=4GB / processors=4` **优先级更高**。
- 推论：想调资源**不要**去改 Docker Desktop 设置面板（改了也不生效），要改 `.wslconfig`；且该文件影响**全部** WSL 发行版（本机还有 Ubuntu / Ubuntu-20.04），改后需 `wsl --shutdown` 才生效 = 顺带重启 docker-desktop VM 与所有容器。

## 根因

Docker Desktop(WSL2 后端)的容器并不直接受自身设置约束, 而是跑在 docker-desktop WSL VM 里, VM 的资源天花板由 `.wslconfig` 的 `[wsl2]` 段决定且优先级高于 `settings-store.json`, 故改设置面板不生效; Resource Saver 的 Auto Pause 则会把 VM 置入损坏的暂停态(cgroup pause 设备丢失), 既不能 resume 也不能正常关闭.

## 解决方案

（自本条其余段落提取）

- 调资源上限改 `C:\Users\<user>\.wslconfig` 的 `[wsl2]` 段（不是 Docker Desktop 设置面板），改后 `wsl --shutdown` 生效；先按边界段判据确认瓶颈确在上限。
- Resource Saver 卡死时：强杀 DD 相关进程 → `wsl --shutdown` → 停-改-起顺序把 `settings-store.json` 的 `UseResourceSaver=false`（CLI 无此开关），改完回读确认未被回写。
- 沙箱内备份文件改存仓库内（写工作区外被限）、用 `explorer.exe "…Docker Desktop.exe"` 拉起 GUI、引擎就绪判定查 `wsl -l -v` 与命名管道而非 `docker version` 轮询。

## 验证

原文实测: `settings-store.json` 为 Cpus:8/MemoryMiB:2048 而 `docker info` 是 CPUs=4 Mem≈4GB(被 `.wslconfig` 覆盖); vmmem 实际占用 2GB/上限 4GB; 宿主 16GB 仅剩 0.7GB; 卡死日志 `pauseError ... cgroup.procs to 0: no such device`。

## 适用边界与反例

- **先判断是否真的被上限卡住**：`Get-Process vmmem | Select WorkingSet64`。若 vmmem 实际占用远低于上限（实测 2GB / 4GB 上限），说明瓶颈不在这个上限，抬上限无收益。
- **容器慢先查宿主内存而非容器配额**：`Win32_OperatingSystem.FreePhysicalMemory`。实测宿主 16GB 仅剩 0.7GB，大户是宿主 App（IDE 类进程可达 2GB+）而非 vmmem；此时给 WSL2 加内存会挤占宿主、加剧换页与磁盘 IO，而磁盘 IO 正是 MySQL InnoDB 初始化慢的直接成因。

### 2. Resource Saver（Auto Pause）会让 Docker Desktop 卡在 `stopping` 无法退出

- 开关不在 `settings-store.json` 明文里时，看合并后的运行时状态：`docker desktop logs` 里搜 `UseResourceSaver` / `AutoPauseTimeoutSeconds` / `AutoPauseTimedActivitySeconds`。
- 触发症状：`docker desktop stop` 永久挂起、`docker desktop status` 恒为 `stopping`，`com.docker.backend.exe.log` 里反复出现
  `pauseError: Got an error resuming Docker Desktop: seeking /sys/fs/cgroup/procd-paused/cgroup.procs to 0: no such device`
  ——VM 处于损坏的暂停态，既不能 resume 也不能正常关闭。
- 关闭方法（CLI 无此开关，只能改文件）：**顺序必须是 停 → 改 → 起**，因为 DD 运行时会持有并在退出时回写该文件。
  ```powershell
  # 1) 停（卡死时须强杀）
  Stop-Process -Name "Docker Desktop","com.docker.backend","com.docker.build" -Force
  wsl --shutdown
  # 2) 改：加/改 UseResourceSaver=false（PowerShell 改 JSON 用 ConvertFrom-Json + Add-Member -Force）
  # 3) 起：见第 3 点
  ```
  改完重启后**必须回读** `settings-store.json` 确认 DD 没把它回写覆盖掉。
- 副作用：关闭 Resource Saver 后闲置期容器不再被暂停，宿主页常驻占用会上升。

### 3. Agent / 沙箱环境下操作 Docker Desktop 的两个限制

- **沙箱禁止写工作区外的文件**：备份 `settings-store.json` 时 `Copy-Item` 到 `%APPDATA%\Docker\` 会 `UnauthorizedAccess`（TRAE Sandbox `hit restricted`），改存到仓库内（如 `<repo>\.docker-settings-store.json.bak`）。读取不受限，仅写入受限。
- **`Start-Process` 启动 GUI 会静默失败**：进程不产生、也不报错（继承受限令牌）。用 `explorer.exe "C:\Program Files\Docker\Docker\Docker Desktop.exe"` 拉起；`docker desktop start` 在此状态下同样无输出。
- 残留的 `Docker Desktop.exe` 僵尸进程（`threads=0`、RSS=0、`taskkill` 报 Access denied、创建于多日前）**不是**阻碍，也不该去强杀（以更高完整性级别运行，普通权限杀不掉）。
- 引擎就绪判定别写 `docker version` 轮询循环——引擎未起时该调用会**长时间阻塞**，把整个循环卡死。改为单次调用 + 直接查 `wsl -l -v` 的 `docker-desktop` 是否 `Running`、`Test-Path "\\.\pipe\dockerDesktopLinuxEngine"`。

### 4. 重启后容器"没起来"多是时序而非故障

- mysql/redis 有 `restart: unless-stopped`，VM 重启后会**自动**回到 Up，无需 `dev.ps1 start`；backend/frontend 无该策略，需再跑一次 `dev.ps1 start`（compose 会复用已 Running 的依赖）。
- 前端 `Invoke-WebRequest http://localhost:5174/` 报"连接被意外关闭"通常是 **Vite 冷启动未就绪**（实测 `ready in 44344 ms`），不是端口冲突；`Get-NetTCPConnection -LocalPort 5174` 会同时看到 `wslrelay`（`::1`）与 `com.docker.backend`（`::`）两条 Listen，这是 WSL2 端口转发的正常形态。
- 验证数据未丢：查 `information_schema.tables` 按 `table_schema` 计数，确认 `fs_uav_area_mark` / `fs_uav_admin` / `fs_uav_auth` 表数与重启前一致。

## 参考

- 源记录: `docs/known-pitfalls/backend/测试与开发环境.md`
