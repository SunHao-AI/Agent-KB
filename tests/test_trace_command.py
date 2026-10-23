import json

import pytest

from kb import trace
from kb.cli import main


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "agent-kb"
    root.mkdir()
    monkeypatch.setattr(trace, "kb_root", lambda: root)
    return root


def _seed(root):
    for i, caller in enumerate(["web", "algo"]):
        trace.append_event({"kind": "search", "trace_id": f"t-1{i}", "ts": f"2026-10-1{i + 4}T10:00:00+08:00",
                            "source": "cli", "caller_repo": caller, "query": f"q{i}",
                            "filters": {}, "limit": 10, "duration_ms": 2,
                            "layers": [], "returned": ["kb-1"] if i == 0 else []}, root=root)


def test_list_empty_guidance(env, capsys):
    assert main(["trace", "list"]) == 0
    out = capsys.readouterr().out
    assert "KB_TRACE" in out           # 引导语指向开关


def test_list_table_and_filters(env, capsys):
    _seed(env)
    assert main(["trace", "list"]) == 0
    out = capsys.readouterr().out
    assert "t-11" in out and "t-10" in out and "0命中" in out
    assert main(["trace", "list", "--caller", "web"]) == 0
    out = capsys.readouterr().out
    assert "t-10" in out and "t-11" not in out
    assert main(["trace", "list", "--since", "2026-10-15"]) == 0
    out = capsys.readouterr().out
    assert "t-11" in out and "t-10" not in out   # seed ts: t-10=10-14, t-11=10-15


def test_show_found_and_missing(env, capsys):
    _seed(env)
    assert main(["trace", "show", "t-10"]) == 0
    assert json.loads(capsys.readouterr().out)["trace_id"] == "t-10"
    assert main(["trace", "show", "nope"]) == 1


def test_list_repo_flag(tmp_path, monkeypatch, capsys):
    # --repo 显式指定时从该根读 traces; 默认根(kb_root)保持无关且为空
    root = tmp_path / "other-agent-kb"
    root.mkdir()
    unused = tmp_path / "unused-root"
    unused.mkdir()
    monkeypatch.setattr(trace, "kb_root", lambda: unused)
    _seed(root)
    assert main(["trace", "list", "--repo", str(root)]) == 0
    out = capsys.readouterr().out
    assert "t-10" in out and "t-11" in out


def test_since_invalid_date_rejected(env, capsys):
    """§58(第四十轮): 字符串比较式日期过滤对非法 --since 静默滤空且 exit 0——
    "暂无记录"冒充"窗口没数据"、周报"已全部消化"假绿。argparse 入口即拒。"""
    _seed(env)
    capsys.readouterr()
    for bad in ("2026-13-99", "垃圾", "2026/10/15"):
        with pytest.raises(SystemExit) as ex:
            main(["trace", "list", "--since", bad])
        assert ex.value.code == 2
        assert "YYYY-MM-DD" in capsys.readouterr().err
    with pytest.raises(SystemExit) as ex:
        main(["trace", "report", "--since", bad])
    assert ex.value.code == 2
    # 合法日期照常
    assert main(["trace", "list", "--since", "2026-10-15"]) == 0
