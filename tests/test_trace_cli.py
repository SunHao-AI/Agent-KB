import json

import pytest
from conftest import make_entry

from kb import trace
from kb.cli import main


@pytest.fixture
def env(tmp_path, monkeypatch):
    """业务仓 Flysee_Web(含索引) + Agent-KB 根指向 tmp, 隔离真实 traces/。"""
    root = tmp_path / "agent-kb"
    root.mkdir()
    monkeypatch.setattr(trace, "kb_root", lambda: root)
    monkeypatch.delenv("KB_TRACE", raising=False)
    proj = tmp_path / "Flysee_Web"
    d = proj / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261012-aaaa", title="Vite HMR 失效",
                                       status="accepted", confidence="verified"),
                            encoding="utf-8")
    (d / "b.md").write_text(make_entry(id="kb-20261012-bbbb", title="无关标题",
                                       tags=["nginx"], status="accepted",
                                       confidence="verified"), encoding="utf-8")
    main(["index", "--repo", str(proj)])
    return root, proj


def _events(root):
    out = []
    for f in sorted((root / "traces").glob("*.jsonl")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            e = json.loads(ln)
            if e.get("kind") != "meta":
                out.append(e)
    return out


def test_off_writes_nothing(env, capsys):
    root, proj = env
    assert main(["search", "--repo", str(proj), "--query", "vite"]) == 0
    assert not (root / "traces").exists()
    assert "kb-20261012-aaaa" in capsys.readouterr().out


def test_flag_on_writes_event(env, capsys):
    root, proj = env
    assert main(["search", "--repo", str(proj), "--query", "vite", "--trace"]) == 0
    out = json.loads(capsys.readouterr().out)   # stdout 仍是纯 JSON 结果
    assert [r["id"] for r in out] == ["kb-20261012-aaaa"]
    evs = _events(root)
    assert len(evs) == 1 and evs[0]["source"] == "cli"
    assert evs[0]["caller_repo"] == "flysee_web"          # resolve().name.lower()
    assert evs[0]["returned"] == ["kb-20261012-aaaa"]
    lay = evs[0]["layers"][0]
    assert lay["scanned"] == 2
    assert lay["rejected"] == {"filter": 0, "query": 1}
    assert lay["matched"][0]["hit_fields"] == ["title"]


def test_no_trace_beats_env(env, monkeypatch):
    root, proj = env
    monkeypatch.setenv("KB_TRACE", "1")
    assert main(["search", "--repo", str(proj), "--query", "vite", "--no-trace"]) == 0
    assert not (root / "traces").exists()


def test_env_on_and_marker(env, monkeypatch):
    root, proj = env
    monkeypatch.setenv("KB_TRACE", "1")
    main(["search", "--repo", str(proj), "--query", "vite"])
    assert len(_events(root)) == 1


def test_flag_and_no_flag_reject_each_other(env):
    _, proj = env
    with pytest.raises(SystemExit):
        main(["search", "--repo", str(proj), "--trace", "--no-trace"])


def test_event_has_no_body(env):
    root, proj = env
    main(["search", "--repo", str(proj), "--query", "vite", "--trace"])
    dump = json.dumps(_events(root), ensure_ascii=False)
    assert "根因" not in dump and "背景" not in dump   # make_entry 正文段名
