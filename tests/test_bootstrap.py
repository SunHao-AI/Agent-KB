import json
import pathlib

import pytest
from conftest import make_entry

from kb.bootstrap import (
    _install_cmd,
    _is_uv_venv,
    doctor,
    doctor_exit_code,
    init_repo,
    render_mcp_json,
)


@pytest.fixture
def fake_layout(tmp_path: pathlib.Path):
    """同级克隆布局: tmp/biz-repo(业务仓, docs/kb + .agent-kb 占位) + tmp/Agent-KB(母本+venv)。"""
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


def test_render_mcp_json_relative_and_lowercase():
    cfg = json.loads(render_mcp_json("Demo-Repo", "docs", ".agent-kb",
                                     "../Agent-KB/.venv/bin/python"))
    srv = cfg["mcpServers"]["kb"]
    assert not pathlib.PurePath(srv["command"]).is_absolute()
    assert srv["command"] == "../Agent-KB/.venv/bin/python"
    assert "cwd" not in srv  # 客户端默认 cwd = .mcp.json 所在目录
    joined = " ".join(srv["args"])
    assert "--repo docs" in joined and "--repo-name demo-repo" in joined


def test_init_writes_executable_relative_command(fake_layout):
    biz, _ak = fake_layout
    info = init_repo(biz / "docs", None, "docs")
    assert info["repo_name"] == "biz-repo"
    assert info["layered"] is True
    srv = json.loads((biz / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["kb"]
    # command 必须相对仓根可直接执行(dogfood 验收口径)
    assert (biz / srv["command"]).exists()
    assert srv["args"][:1] == ["-m"] and ".agent-kb" in srv["args"]


def test_init_creates_kb_skeleton_for_first_onboarding(fake_layout):
    biz, _ak = fake_layout
    info = init_repo(biz / "docs", None, "knowledge")
    assert info["kb_dir_created"] is True
    assert (biz / "knowledge" / "kb").is_dir()


def test_init_without_submodule_degrades_to_single_layer(fake_layout):
    biz, _ak = fake_layout
    (biz / ".agent-kb").rmdir()
    info = init_repo(biz / "docs", None, "docs")
    assert info["layered"] is False
    srv = json.loads((biz / ".mcp.json").read_text(encoding="utf-8"))["mcpServers"]["kb"]
    assert "--agent-kb" not in srv["args"]
    assert (biz / srv["command"]).exists()  # 仍指同级主仓 venv, 可直接执行


def test_init_refuses_overwrite_without_force(fake_layout):
    biz, _ak = fake_layout
    init_repo(biz / "docs", None, "docs")
    with pytest.raises(FileExistsError):
        init_repo(biz / "docs", None, "docs")
    init_repo(biz / "docs", None, "docs", force=True)


def test_init_requires_agent_kb_inside_repo(fake_layout):
    biz, ak = fake_layout
    with pytest.raises(FileNotFoundError):
        init_repo(biz / "docs", ak, "docs")  # 显式指定的 --agent-kb 在仓外


def test_doctor_flags_missing_venv(fake_layout):
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
    init_repo(biz / "docs", None, "docs")
    checks = doctor(biz / "docs", agent_kb=ak)
    by_name = {n: (lvl, msg) for lvl, n, msg in checks}
    assert by_name["agent-kb venv (mcp)"][0] == "PASS"
    assert by_name[".mcp.json"][0] == "PASS"  # 相对 command 存在 → PASS
    assert by_name["kb lint"][0] == "PASS"
    # 未装门禁钩子/索引未建 → 只 WARN 不 FAIL
    assert doctor_exit_code(checks) == 0


def test_doctor_index_fresh_uses_carrier_name(fake_layout, monkeypatch):
    """§45 第二十七轮: index fresh 的 repo_name 必须与 `kb index` CLI 默认口径
    一致(kb 载体目录名小写)。旧实现用业务仓根名(biz-repo), docs/kb 结构下与
    index.jsonl 现值(docs)恒不等 → 刚 kb index 过的仓 doctor 仍恒报 stale,
    且按建议重建也永远消不掉。主仓 kb 恰好载体=仓根同名, 自测掩盖了漂移。"""
    from kb.index import build_indexes
    biz, ak = fake_layout
    (biz / "docs" / "kb" / "pitfall" / "backend" / "a.md").write_text(
        make_entry(id="kb-20261022-a1a1", status="accepted", confidence="verified"),
        encoding="utf-8")
    build_indexes(biz / "docs", repo_name="docs")   # 与 CLI 默认口径一致的构建
    from kb import bootstrap
    monkeypatch.setattr(bootstrap, "_mod_ok", lambda *a, **k: True)
    checks = doctor(biz / "docs", agent_kb=ak)
    by_name = {n: (lvl, msg) for lvl, n, msg in checks}
    assert by_name["index fresh"][0] == "PASS", by_name["index fresh"]


def test_doctor_index_fresh_uses_persisted_label(fake_layout, monkeypatch):
    """index fresh 的 repo 标签必须从 index.jsonl 自取, 不从载体目录名反推。

    真实业务仓的 kb 载体是 docs/, 但生成时写进 repo 字段的是**仓名**(kb init/CI
    口径), 不是 "docs"。上一轮把口径从"业务仓根名"改成"载体目录名", 仍是从可变
    挂载点反推固化值 → 换一种布局继续恒 WARN, 而 doctor 是唯一能一次覆盖全仓的
    检查面, 恒假阳性等于没有检查(通用层索引过期数月无人发现)。
    """
    from kb.index import build_indexes
    biz, ak = fake_layout
    (biz / "docs" / "kb" / "pitfall" / "backend" / "a.md").write_text(
        make_entry(id="kb-20261101-b1b1", status="accepted", confidence="verified"),
        encoding="utf-8")
    build_indexes(biz / "docs", repo_name="biz-repo")   # 固化标签 = 仓名 ≠ 载体名 docs
    from kb import bootstrap
    monkeypatch.setattr(bootstrap, "_mod_ok", lambda *a, **k: True)
    checks = doctor(biz / "docs", agent_kb=ak)
    by_name = {n: (lvl, msg) for lvl, n, msg in checks}
    assert by_name["index fresh"][0] == "PASS", by_name["index fresh"]


def test_doctor_warns_stale_submodule_pointer(fake_layout, monkeypatch):
    """submodule 指针停在旧提交 = 通用层一直在服务过期语料, doctor 必须报出来。

    `.gitmodules` 配 branch = master 只是声明, 没人 fetch 就没人知道落后(2026-11-01
    实测三仓指针停在数月前, 通用层 sections 字段整层缺失)。这里只读本地引用:
    同级主仓 HEAD 的对象在 submodule 内可解析时, 离线即可算出落后数。
    """
    from kb import bootstrap
    biz, ak = fake_layout
    (biz / ".gitmodules").write_text(
        '[submodule ".agent-kb"]\n\tpath = .agent-kb\n\turl = https://x/agent.git\n'
        "\tbranch = master\n", encoding="utf-8")
    (biz / ".agent-kb" / "kb").mkdir(parents=True)      # 非空 = 已 checkout
    (biz / ".agent-kb" / ".git").write_text("gitdir: x\n", encoding="utf-8")
    monkeypatch.setattr(bootstrap, "_mod_ok", lambda *a, **k: True)
    (biz / ".venv" / "Scripts").mkdir(parents=True)      # 门禁 venv 齐备, 只考察指针项
    (biz / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
    refs = {"HEAD": "aaa", "origin/master": None}

    def fake_git_out(args):
        if args[:3] == ["-C", str(ak), "rev-parse"]:
            return "bbb"                                 # 同级主仓 HEAD
        if args[-1] == "HEAD":
            return refs["HEAD"]
        if args[-1].startswith("bbb"):
            return ""                                    # cat-file -e: 对象可见(空输出=成功)
        if args[-1].startswith("HEAD.."):
            return "37"
        if args[-1] == "origin/master":
            return refs["origin/master"]
        return None

    monkeypatch.setattr(bootstrap, "_git_out", fake_git_out)
    checks = doctor(biz / "docs", agent_kb=ak)
    by_name = {n: (lvl, msg) for lvl, n, msg in checks}
    assert by_name["submodule pointer"][0] == "WARN"
    assert "37" in by_name["submodule pointer"][1]
    assert doctor_exit_code(checks) == 0                 # 只 WARN 不 FAIL


def test_doctor_submodule_pointer_up_to_date_passes(fake_layout, monkeypatch):
    """origin/<branch> 与指针齐平时判"不落后"。旧写法先过滤掉相等的参照, 结果
    参照集为空 → 误报"无从判定", 恰好把最需要确认的正常态说成不可知。"""
    from kb import bootstrap
    biz, ak = fake_layout
    (biz / ".gitmodules").write_text(
        '[submodule ".agent-kb"]\n\tpath = .agent-kb\n\tbranch = master\n', encoding="utf-8")
    (biz / ".agent-kb" / "kb").mkdir(parents=True)
    monkeypatch.setattr(bootstrap, "_mod_ok", lambda *a, **k: True)
    (biz / ".venv" / "Scripts").mkdir(parents=True)
    (biz / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")

    def fake_git_out(args):
        if args[:3] == ["-C", str(ak), "rev-parse"]:
            return None                                  # 主仓不可比
        if args[-1] in ("HEAD", "origin/master", "ccc"):
            return "ccc" if args[-1] != "HEAD" else "ccc"
        if args[-1].startswith("HEAD.."):
            return "0"
        return None

    monkeypatch.setattr(bootstrap, "_git_out", fake_git_out)
    checks = doctor(biz / "docs", agent_kb=ak)
    by_name = {n: (lvl, msg) for lvl, n, msg in checks}
    lvl, msg = by_name["submodule pointer"]
    assert lvl == "PASS" and "origin/master" in msg, by_name["submodule pointer"]


def test_doctor_submodule_pointer_notes_unfetched_main_tip(fake_layout, monkeypatch):
    """主仓已前进但新对象没 fetch 进 submodule 时, "不落后"必须带出这一限定。

    origin/<branch> 只是上次 fetch 的快照: 指针与快照齐平不代表通用层追上了主仓。
    只报"不落后"会把"主仓有新东西"藏起来 —— 本检查存在的理由就是消灭这种虚假
    安全感, 故 PASS 也要如实标注参照的时效边界。
    """
    from kb import bootstrap
    biz, ak = fake_layout
    (biz / ".gitmodules").write_text(
        '[submodule ".agent-kb"]\n\tpath = .agent-kb\n\tbranch = master\n', encoding="utf-8")
    (biz / ".agent-kb" / "kb").mkdir(parents=True)
    monkeypatch.setattr(bootstrap, "_mod_ok", lambda *a, **k: True)
    (biz / ".venv" / "Scripts").mkdir(parents=True)
    (biz / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")

    def fake_git_out(args):
        if args[:3] == ["-C", str(ak), "rev-parse"]:
            return "d" * 40                                # 主仓已前进
        if args[-1] == "HEAD":
            return "c" * 40
        if args[-1] == "origin/master":
            return "c" * 40                                # 快照与指针齐平
        if args[-2:] == ["-e", "d" * 40 + "^{commit}"]:
            return None                                    # 新对象未 fetch 进 submodule
        if args[-1].startswith("HEAD.."):
            return "0"
        return None

    monkeypatch.setattr(bootstrap, "_git_out", fake_git_out)
    checks = doctor(biz / "docs", agent_kb=ak)
    lvl, msg = {n: (lvl, msg) for lvl, n, msg in checks}["submodule pointer"]
    assert lvl == "PASS"
    assert "origin/master" in msg and "未 fetch" in msg, msg


def test_submodule_branch_parses_gitmodules(tmp_path):
    from kb.bootstrap import _submodule_branch
    gm = tmp_path / ".gitmodules"
    gm.write_text('[submodule ".agent-kb"]\n\tpath = .agent-kb\n\tbranch = master\n',
                  encoding="utf-8")
    assert _submodule_branch(gm) == "master"
    gm.write_text('[submodule "other"]\n\tpath = other\n\tbranch = dev\n'
                  '[submodule ".agent-kb"]\n\tpath = .agent-kb\n', encoding="utf-8")
    assert _submodule_branch(gm) is None                 # 别的 submodule 的 branch 不得串味


def test_doctor_abs_path_mcp_command_warns(fake_layout):
    biz, ak = fake_layout
    (biz / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"kb": {"command": "d:/abs/python.exe", "args": []}}}),
        encoding="utf-8")
    checks = doctor(biz / "docs", agent_kb=ak)
    assert any(lvl == "WARN" and n == ".mcp.json" for lvl, n, _ in checks)


def test_doctor_dead_relative_command_fails(fake_layout):
    biz, ak = fake_layout
    (biz / ".mcp.json").write_text(json.dumps(
        {"mcpServers": {"kb": {"command": "../gone/.venv/bin/python", "args": []}}}),
        encoding="utf-8")
    checks = doctor(biz / "docs", agent_kb=ak)
    assert any(lvl == "FAIL" and n == ".mcp.json" for lvl, n, _ in checks)


def test_install_cmd_uv_vs_std(tmp_path):
    biz = tmp_path / "biz"
    (biz / ".venv").mkdir(parents=True)
    # 标准 venv → python -m pip
    (biz / ".venv" / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")
    assert _is_uv_venv(biz) is False
    assert "-m pip install" in _install_cmd(biz, ".venv/bin/python", "pytest")
    # uv venv → uv pip install --python (uv venv 无 pip, 给 pip 是死路)
    (biz / ".venv" / "pyvenv.cfg").write_text("home = x\nuv = 0.9.17\n", encoding="utf-8")
    assert _is_uv_venv(biz) is True
    cmd = _install_cmd(biz, ".venv/Scripts/python.exe", "pytest ruff")
    assert cmd.startswith("uv pip install pytest ruff --python ")
    assert cmd.endswith("biz/.venv/Scripts/python.exe")  # 绝对解释器路径, 可直接粘贴


def test_is_uv_venv_substring_not_misjudged(tmp_path):
    """§74(第五十七轮): 旧实现全文子串 "uv" in text——标准 venv 的 command 行
    恰含 uv 子串(用户名 uvuser)即误判, doctor 开出机器上没有的 uv 命令。
    文档承诺的是 `uv = <ver>` 键行, 必须行级键匹配。"""
    biz = tmp_path / "biz"
    (biz / ".venv").mkdir(parents=True)
    (biz / ".venv" / "pyvenv.cfg").write_text(
        "home = /home/uvuser/.pyenv/versions/3.12\n"
        "version = 3.12.4\n"
        "command = /home/uvuser/.pyenv/.../python -m venv /home/uvuser/x/.venv\n",
        encoding="utf-8")
    assert _is_uv_venv(biz) is False
    assert "-m pip install" in _install_cmd(biz, ".venv/bin/python", "pytest")


def test_doctor_gate_missing_dep_hints_uv_command(fake_layout, monkeypatch):
    biz, ak = fake_layout
    from kb import bootstrap
    monkeypatch.setattr(bootstrap, "_mod_ok", lambda *a, **k: False)  # 全缺依赖
    (biz / ".venv" / "Scripts").mkdir(parents=True)
    (biz / ".venv" / "Scripts" / "python.exe").write_text("", encoding="utf-8")
    (biz / ".venv" / "pyvenv.cfg").write_text("uv = 0.7.11\n", encoding="utf-8")
    checks = doctor(biz / "docs", agent_kb=ak)
    pytest_line = next(msg for lvl, n, msg in checks if n == "gate pytest")
    assert "uv pip install" in pytest_line and "pip install -e" not in pytest_line
