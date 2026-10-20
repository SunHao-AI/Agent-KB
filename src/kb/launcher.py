"""kb web — 瘦客户端启动器(PRD FR-2.1 / FR-2.5 单人态)。

发现链(单人态; 团队态 serve_url 属 B-4):
1. 探活目标端口 → 有 serve 直连;
2. 无 serve → 后台代拉起 `kb serve --default-caller <本项目>`(detached),
   等待就绪后打开浏览器; serve 常驻, 由维护者或系统管理器负责停。
项目身份推断(FR-5.1): 当前目录名小写 = caller_repo 口径(与埋点同源)。
在 Agent-KB 仓根启动 → caller=None(联邦视图, 维护者默认)。

注: 模块名不叫 web.py —— 与静态资源包 kb/web/ 冲突(package 优先)。
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

from kb import trace as kbtrace


def probe_port(port: int, host: str = "127.0.0.1", timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def infer_caller(cwd: Path | None = None) -> str | None:
    """Agent-KB 仓根 → None(联邦); 其他目录 → 目录名小写(单项目)。

    caller 口径与埋点同源(目录名小写), 不做跨机 path 匹配(PRD 同名冲突观察项)。
    """
    cwd = Path(cwd or Path.cwd()).resolve()
    if cwd == kbtrace.kb_root().resolve():
        return None
    return cwd.name.lower()


def spawn_serve(root: Path, port: int, default_caller: str | None,
                token: str | None = None) -> None:
    """detached 代拉起 serve(单人态, 仅 127.0.0.1)。"""
    cmd = [sys.executable, "-m", "kb.serve", "--repo", str(root), "--port", str(port)]
    if default_caller:
        cmd += ["--default-caller", default_caller]
    if token:
        cmd += ["--token", token]
    kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    subprocess.Popen(cmd, **kwargs)


def open_page(port: int, no_browser: bool = False) -> str:
    url = f"http://127.0.0.1:{port}/"
    if not no_browser:
        webbrowser.open(url)
    return url


def probe_http(base: str, token: str | None = None, timeout: float = 1.5) -> bool:
    """团队实例探活: GET /healthz(Bearer)。任何异常都算不可达。"""
    from urllib.request import Request, urlopen
    try:
        req = Request(base.rstrip("/") + "/healthz")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        with urlopen(req, timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def open_panel(port: int = 4320, *, repo: Path | None = None, caller: str | None = "",
               all_projects: bool = False, no_browser: bool = False,
               token: str | None = None, wait_sec: float = 8.0) -> tuple[str, str]:
    """返回 (最终 URL, 模式说明)。caller='' 表示自动推断; None=联邦; str=指定项目。

    发现链(FR-2.5): ~/.kb/config.toml [serve].url 可达 → 连团队实例(mode=team);
    不可达 → 横幅式提示由前端呈现, 这里降级本机(mode=local-degraded)。
    单人态: 探活本机端口, 不通则代拉起。
    """
    from kb.userconf import serve_target
    root = Path(repo) if repo else kbtrace.kb_root()
    resolved = infer_caller() if caller == "" else caller
    if all_projects:
        resolved = None
    suffix = "?caller=*" if all_projects else (f"?caller={resolved}" if resolved else "")
    team_url, team_token = serve_target()
    if team_url and probe_http(team_url, team_token):
        tok = team_token or token
        url = team_url.rstrip("/") + "/" + suffix
        if tok:
            url += ("&" if "?" in url else "?") + f"token={tok}"
        if not no_browser:
            webbrowser.open(url)
        return url, f"team: {team_url}"
    degraded = bool(team_url)  # 配了团队地址但连不上 → 降级(前端横幅明示)
    if not probe_port(port):
        spawn_serve(root, port, resolved, token=token)
        t0 = time.monotonic()
        while not probe_port(port):
            if time.monotonic() - t0 > wait_sec:
                raise RuntimeError(
                    f"kb serve 拉起失败: 127.0.0.1:{port} 等待 {wait_sec}s 无响应; "
                    f"可手动运行 kb serve --repo {root} 查看报错")
            time.sleep(0.25)
    url = f"http://127.0.0.1:{port}/{suffix}"
    if degraded:  # 前端据 degraded=1 挂横幅: "已配置团队实例但不可达"(FR-2.5 禁演"没数据")
        url += ("&" if "?" in url else "?") + "degraded=1&serve_url=" + team_url
    if not no_browser:
        webbrowser.open(url)
    return url, "local-degraded" if degraded else "local"
