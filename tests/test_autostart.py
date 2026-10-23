"""A-2 FR-2.5: 自启动安装的纯函数面(渲染/命令拼装), 不真碰系统管理器。"""
import pathlib
import sys

import pytest

from kb import autostart


def test_serve_command_uses_current_interpreter(tmp_path):
    cmd, args, wd = autostart.serve_command(tmp_path, 4321, "127.0.0.1", None)
    assert cmd == sys.executable
    assert "-m kb.serve" in args and "--port 4321" in args
    assert wd == str(tmp_path)
    assert "token" not in args.lower()  # 红线: token 永不进任务定义


def test_serve_command_quoted_path_and_caller(tmp_path):
    repo = tmp_path / "my repo"
    _, args, _ = autostart.serve_command(repo, 4320, "127.0.0.1", "my repo")
    assert f'"{repo}"' in args           # 含空格的值必须加引号防拆参
    assert '--default-caller "my repo"' in args
    _, args2, _ = autostart.serve_command(tmp_path, 4320, "127.0.0.1", "web")
    assert args2.endswith("--default-caller web")  # 无空格不加引号


def test_install_windows_escapes_single_quotes(monkeypatch, tmp_path):
    """§72(第五十五轮): install_windows 把 repo 路径/default_caller 裸插
    PowerShell 单引号串, 含单引号即断串——路径含 ' 安装必炸, --default-caller
    含 `'; <命令>; '` 是命令注入原语。修复: 单引号按 PS 规则加倍(' → '')。"""
    captured = {}
    monkeypatch.setattr(autostart, "_ps",
                        lambda s: captured.__setitem__("s", s) or (0, "ok"))
    repo = tmp_path / "O'Brien"          # 用户名含单引号
    autostart.install_windows(repo, 4320, "127.0.0.1", "evil'; Get-Process; '")
    ps = captured["s"]
    assert "O''Brien" in ps              # 路径单引号加倍转义
    assert "evil''; Get-Process; ''" in ps  # caller 注入被转义成字面量
    # 断串判据: 从 -Execute 起, 每个单引号串都必须成对(加倍后不再有孤立闭合)
    assert ps.count("'") % 2 == 0


def test_systemd_unit_shape():
    unit = autostart.render_systemd_unit("/usr/bin/python3", "-m kb.serve", "/srv/kb")
    assert "ExecStart=/usr/bin/python3 -m kb.serve" in unit
    assert "Restart=on-failure" in unit and "WantedBy=default.target" in unit
    assert "KB_SERVE_TOKEN=" not in unit.split("set-environment")[0]  # 令牌只出现在注释指引里


def test_render_systemd_unit_rejects_newline_injection():
    """§72 同族(第五十六轮): unit 文件"值不跨行"是载体不变量且 systemd 无值内
    换行转义, `--default-caller "evil\\nExecStartPre=…"` 曾注入新指令行(探针实锤)。
    渲染入口必须 fail-loud 拒收。"""
    _, args, _ = autostart.serve_command(
        pathlib.Path("/srv/kb"), 4320, "127.0.0.1",
        "evil\nExecStartPre=/bin/sh -c pwned")
    with pytest.raises(ValueError, match="换行"):
        autostart.render_systemd_unit("/usr/bin/python3", args, "/srv/kb")
