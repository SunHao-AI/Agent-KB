import json
import pathlib

import pytest

from kb.bootstrap import doctor, doctor_exit_code, init_repo, render_mcp_json


@pytest.fixture
def fake_layout(tmp_path: pathlib.Path):
    """同级克隆布局: tmp/repo(业务仓, docs/kb + .agent-kb 占位) + tmp/Agent-KB(母本+venv)。"""
    biz = tmp_path / "biz-repo"
    (biz / "docs" / "kb" / "pitfall" / "backend").mkdir(parents=True)
    (biz / ".agent-kb").mkdir()
    ak = tmp_path / "Agent-KB"
    (ak / "src" / "kb").mkdir(parents=True)
    (ak / "scripts").mkdir()
    (ak / "scripts" / "pre-push-gate.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    (ak / ".venv" / "Scripts").mkdir(parents=True)
    (ak / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
    return biz, ak


def test_render_mcp_json_relative_interpreter_template():
    cfg = json.loads(render_mcp_json("Demo-Repo", "docs", ".agent-kb"))
    srv = cfg["mcpServers"]["kb"]
    assert srv["command"] == "{interpreter}"
    assert not pathlib.PurePath(srv["command"]).is_absolute()
    assert srv["cwd"] == ".agent-kb"
    joined = " ".join(srv["args"])
    assert "--repo docs" in joined and "--repo-name demo-repo" in joined


def test_init_writes_mcp_json_and_guidance(fake_layout):
    biz, _ak = fake_layout
    info = init_repo(biz, None, "docs")
    assert info["repo_name"] == "biz-repo"
    assert info["interpreter"] in (".venv/bin/python", ".venv/Scripts/python.exe")
    srv = json.loads((biz / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["kb"]
    assert srv["command"] == "{interpreter}"
    assert srv["cwd"] == ".agent-kb"


def test_init_refuses_overwrite_without_force(fake_layout):
    biz, _ak = fake_layout
    init_repo(biz, None, "docs")
    with pytest.raises(FileExistsError):
        init_repo(biz, None, "docs")
    init_repo(biz, None, "docs", force=True)


def test_init_requires_kb_dir_and_agent_kb_inside_repo(fake_layout):
    biz, _ak = fake_layout
    with pytest.raises(FileNotFoundError):
        init_repo(biz, None, "no-such-dir")
    with pytest.raises(FileNotFoundError):
        init_repo(biz, biz.parent, "docs")  # --agent-kb 在仓外


def test_doctor_flags_missing_venv_and_reports_mcp_template(fake_layout):
    biz, ak = fake_layout
    (ak / ".venv" / "Scripts" / "python.exe").unlink()
    checks = doctor(biz / "docs", agent_kb=ak)
    fails = {n for lvl, n, _ in checks if lvl == "FAIL"}
    assert "agent-kb venv (mcp)" in fails
    assert doctor_exit_code(checks) == 1


def test_doctor_green_paths_on_prepared_layout(fake_layout, monkeypatch):
    biz, ak = fake_layout
    from kb import bootstrap
    monkeypatch.setattr(bootstrap, "_mod_ok", lambda *a, **k: True)  # 假 venv 不可执行
    (biz / ".venv" / "Scripts").mkdir(parents=True)
    (biz / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
    init_repo(biz, None, "docs")
    checks = doctor(biz / "docs", agent_kb=ak)
    by_name = {n: lvl for lvl, n, _ in checks}
    assert by_name["agent-kb venv (mcp)"] == "PASS"
    assert by_name[".mcp.json"] == "PASS"
    assert by_name["kb lint"] == "PASS"
    # 未装门禁钩子/索引未建 → 只 WARN 不 FAIL
    assert doctor_exit_code(checks) == 0


def test_doctor_abs_path_mcp_command_warns(fake_layout):
    biz, ak = fake_layout
    (biz / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"kb": {"command": "d:/abs/python.exe", "args": []}}}),
        encoding="utf-8")
    checks = doctor(biz / "docs", agent_kb=ak)
    assert any(lvl == "WARN" and n == ".mcp.json" for lvl, n, _ in checks)
