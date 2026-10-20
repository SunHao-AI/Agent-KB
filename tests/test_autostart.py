"""A-2 FR-2.5: 自启动安装的纯函数面(渲染/命令拼装), 不真碰系统管理器。"""
import sys

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


def test_systemd_unit_shape():
    unit = autostart.render_systemd_unit("/usr/bin/python3", "-m kb.serve", "/srv/kb")
    assert "ExecStart=/usr/bin/python3 -m kb.serve" in unit
    assert "Restart=on-failure" in unit and "WantedBy=default.target" in unit
    assert "KB_SERVE_TOKEN=" not in unit.split("set-environment")[0]  # 令牌只出现在注释指引里
