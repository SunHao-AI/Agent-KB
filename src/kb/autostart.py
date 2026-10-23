"""kb serve --install-autostart — 交系统服务管理器常驻(PRD FR-2.5, 不自造守护)。

Windows: 计划任务(schtasks, 用户登录触发); Linux/macOS(systemd): 用户级 unit。
幂等: 重复安装 = 覆盖刷新; 卸载对不存在的目标静默成功。
红线: token 永不落盘 —— 生成的任务/unit 只含 serve 命令行; 需要鉴权时由用户
自行注入系统级环境变量(KB_SERVE_TOKEN), 任务继承后生效。
"""
from __future__ import annotations

import platform
import subprocess
import sys
from pathlib import Path

TASK_NAME = "kb-serve"
UNIT_NAME = "kb-serve.service"


def serve_command(repo: Path, port: int, bind: str,
                  default_caller: str | None) -> tuple[str, str, str]:
    """(command, args, working_dir) — 用当前解释器直跑 kb.serve, 不依赖 PATH。"""
    args = ["-m", "kb.serve", "--repo", str(repo), "--port", str(port),
            "--bind", bind]
    if default_caller:
        args += ["--default-caller", default_caller]
    return (sys.executable,
            " ".join(f'"{a}"' if " " in str(a) else str(a) for a in args),
            str(repo))


def render_systemd_unit(command: str, args: str, working_dir: str) -> str:
    # §72 同族(第五十六轮): unit 文件的载体不变量是"值不跨行"(换行=新指令行,
    # systemd 无值内换行转义)。`--default-caller "evil\nExecStartPre=…"` 曾直接
    # 注入新指令行(探针实锤 ExecStartPre 落盘)。systemd 没有可依赖的值内转义,
    # 唯一正确姿势是渲染入口 fail-loud 拒收——这是安装参数, 报错比装出坏 unit 好。
    for name, v in (("command", command), ("args", args), ("working_dir", working_dir)):
        if any(ch in str(v) for ch in ("\n", "\r")):
            raise ValueError(f"systemd unit 字段 {name} 含换行, 拒绝渲染"
                             f"(unit 值跨行会被解析成新指令行)")
    return (f"[Unit]\n"
            f"Description=Agent-KB kb serve (managed by kb serve --install-autostart)\n"
            f"\n[Service]\n"
            f"ExecStart={command} {args}\n"
            f"WorkingDirectory={working_dir}\n"
            f"Restart=on-failure\n"
            f"RestartSec=5\n"
            f"# 令牌不落盘红线: 需要鉴权请执行\n"
            f"#   systemctl --user set-environment KB_SERVE_TOKEN=<令牌>\n"
            f"# 或写入 ~/.config/environment.d/ 后 restart 本 unit\n"
            f"\n[Install]\n"
            f"WantedBy=default.target\n")


def _run(cmd: list[str]) -> tuple[int, str]:
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    return r.returncode, (r.stdout + r.stderr).strip()


# ---------------- Windows 计划任务(PowerShell cmdlet) ----------------
# 注: schtasks.exe 在部分受管终端被策略拦截(Access denied), Register-ScheduledTask
# cmdlet 走不同 API 实测可通, 故用 cmdlet 为主路径。

def _ps(script: str) -> tuple[int, str]:
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])


def _psq(s: str) -> str:
    """PowerShell 单引号串内转义: 唯一的转义规则是 ' → ''。路径含单引号
    (用户名 O'Brien 等)时旧实现裸插值直接断串——注册失败且报错指向 cmdlet
    而非真因; --default-caller 是任意 CLI 串, 含 `'; <命令>; '` 即在本机
    用户上下文执行任意命令(自伤面为主, 但这是命令注入的原语级缺陷)。"""
    return str(s).replace("'", "''")


def install_windows(repo: Path, port: int, bind: str,
                    default_caller: str | None,
                    tmp_dir: Path | None = None) -> str:
    cmd, args, wd = serve_command(repo, port, bind, default_caller)
    # cmdlet 原生参数路径(非 -Xml): 受管环境下 -Xml 注册会被策略拒(0x80070005)。
    # 触发器必须 -User 绑定当前用户: 不带 = "任意用户登录"语义, 需管理员权限(实测被拒)。
    ps = ("$a=New-ScheduledTaskAction -Execute '{cmd}' -Argument '{args}' -WorkingDirectory '{wd}'; "
          "$t=New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME; "
          "$si=New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries "
          "-DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) "
          "-RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1); "
          "Register-ScheduledTask -TaskName {TASK_NAME} -Action $a -Trigger $t "
          "-Settings $si -Force | Out-Null; "
          "Start-ScheduledTask -TaskName {TASK_NAME}").format(cmd=_psq(cmd),
                                                              args=_psq(args),
                                                              wd=_psq(wd),
                                                              TASK_NAME=TASK_NAME)
    rc, msg = _ps(ps)
    if rc != 0:
        raise RuntimeError(f"计划任务注册失败(可能需要管理员权限?): {msg}")
    return (f"计划任务 {TASK_NAME} 已注册并启动(登录触发, 崩溃后系统重拉)。"
            f"查看: Get-ScheduledTask -TaskName {TASK_NAME}; "
            f"卸载: kb serve --uninstall-autostart; "
            f"令牌注入(不落盘): setx KB_SERVE_TOKEN <令牌> 后重登")


def uninstall_windows() -> str:
    rc, msg = _ps(f"Unregister-ScheduledTask -TaskName {TASK_NAME} -Confirm:$false")
    low = msg.lower()
    if rc != 0 and ("cannot find" in low or "找不到" in msg or "not found" in low):
        return f"计划任务 {TASK_NAME} 本就不存在, 无需卸载"
    if rc != 0:
        raise RuntimeError(f"计划任务删除失败: {msg}")
    return f"计划任务 {TASK_NAME} 已删除"


# ---------------- systemd 用户级 unit ----------------

def install_systemd(repo: Path, port: int, bind: str,
                    default_caller: str | None) -> str:
    cmd, args, wd = serve_command(repo, port, bind, default_caller)
    unit = Path.home() / ".config" / "systemd" / "user" / UNIT_NAME
    unit.parent.mkdir(parents=True, exist_ok=True)
    unit.write_text(render_systemd_unit(cmd, args, wd), encoding="utf-8")
    rc, msg = _run(["systemctl", "--user", "daemon-reload"])
    if rc != 0:
        raise RuntimeError(f"systemctl daemon-reload 失败: {msg}")
    rc, msg = _run(["systemctl", "--user", "enable", "--now", UNIT_NAME])
    if rc != 0:
        raise RuntimeError(f"启用 unit 失败: {msg}")
    return (f"{unit} 已安装并启动(enable --now, 幂等覆盖)。"
            f"令牌注入(不落盘): systemctl --user set-environment KB_SERVE_TOKEN=<令牌>")


def uninstall_systemd() -> str:
    unit = Path.home() / ".config" / "systemd" / "user" / UNIT_NAME
    _run(["systemctl", "--user", "disable", "--now", UNIT_NAME])  # 未装也静默
    if unit.exists():
        unit.unlink()
    _run(["systemctl", "--user", "daemon-reload"])
    return f"{unit} 已卸载"


def install(repo: Path, port: int, bind: str,
            default_caller: str | None) -> str:
    if platform.system() == "Windows":
        return install_windows(repo, port, bind, default_caller)
    return install_systemd(repo, port, bind, default_caller)


def uninstall() -> str:
    if platform.system() == "Windows":
        return uninstall_windows()
    return uninstall_systemd()
