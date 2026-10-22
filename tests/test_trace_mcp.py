import json

import pytest
from conftest import make_entry
from mcp.shared.memory import create_connected_server_and_client_session

from kb import trace
from kb.index import build_indexes
from kb.mcp_server import build_server

pytestmark = pytest.mark.asyncio


async def _call(server, name, args):
    async with create_connected_server_and_client_session(server) as client:
        res = await client.call_tool(name, args)
        return res.isError, res.content[0].text


@pytest.fixture
def env(tmp_path, monkeypatch):
    root = tmp_path / "agent-kb"
    root.mkdir()
    monkeypatch.setattr(trace, "kb_root", lambda: root)
    monkeypatch.delenv("KB_TRACE", raising=False)
    proj = tmp_path / "docs"
    d = proj / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261012-aaaa", title="Vite HMR 抖动",
                                       status="accepted", confidence="verified")
                            + "\n## 根因\n项目层机制说明文本。\n", encoding="utf-8")
    build_indexes(proj, repo_name="docs")
    return root, proj


def _events(root):
    out = []
    for f in sorted((root / "traces").glob("*.jsonl")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            e = json.loads(ln)
            if e.get("kind") != "meta":
                out.append(e)
    return out


async def test_mcp_off_writes_nothing(env):
    root, proj = env
    srv = build_server(proj, [], repo_name="docs")
    err, _ = await _call(srv, "kb_search", {"query": "Vite"})
    assert err is False
    assert not (root / "traces").exists()


async def test_search_event_written(env, monkeypatch):
    root, proj = env
    monkeypatch.setenv("KB_TRACE", "1")
    srv = build_server(proj, [], repo_name="docs")
    err, text = await _call(srv, "kb_search", {"query": "Vite"})
    assert err is False and json.loads(text)[0]["id"] == "kb-20261012-aaaa"
    evs = _events(root)
    assert len(evs) == 1 and evs[0]["source"] == "mcp"
    assert evs[0]["caller_repo"] == "docs"
    assert evs[0]["returned"] == ["kb-20261012-aaaa"]
    assert evs[0]["layers"][0]["matched"][0]["hit_fields"] == ["title"]


async def test_get_links_to_recent_search(env, monkeypatch):
    root, proj = env
    monkeypatch.setenv("KB_TRACE", "1")
    srv = build_server(proj, [], repo_name="docs")
    await _call(srv, "kb_search", {"query": "Vite"})
    sid = _events(root)[0]["trace_id"]
    await _call(srv, "kb_get", {"id": "kb-20261012-aaaa"})
    get_ev = _events(root)[1]
    assert get_ev["kind"] == "get" and get_ev["id"] == "kb-20261012-aaaa"
    assert get_ev["trace_id"] == sid and get_ev["layer"] == "docs" and get_ev["ok"] is True


async def test_get_after_unrelated_search_links_to_returning_one(env, monkeypatch):
    """§40 端到端: search(命中) → search(零命中) → get(首轮条目)。旧实现挂最近
    一次(零命中那次), 消费判定判未消费; 修复后应挂回返回过它的首轮 trace。"""
    root, proj = env
    monkeypatch.setenv("KB_TRACE", "1")
    srv = build_server(proj, [], repo_name="docs")
    await _call(srv, "kb_search", {"query": "Vite"})
    sid1 = _events(root)[0]["trace_id"]
    await _call(srv, "kb_search", {"query": "完全不存在的词zzz"})   # 最近一次, 零命中
    await _call(srv, "kb_get", {"id": "kb-20261012-aaaa"})
    get_ev = _events(root)[2]
    assert get_ev["kind"] == "get" and get_ev["ok"] is True
    assert get_ev["trace_id"] == sid1, "get 应关联到返回过该条目的首轮 search"


async def test_get_miss_records_ok_false(env, monkeypatch):
    root, proj = env
    monkeypatch.setenv("KB_TRACE", "1")
    srv = build_server(proj, [], repo_name="docs")
    err, _ = await _call(srv, "kb_get", {"id": "kb-00000000-0000"})
    assert err is True                      # 工具仍报错
    ev = _events(root)[-1]
    assert ev["kind"] == "get" and ev["ok"] is False and ev["layer"] is None


def test_mcp_cli_trace_flag_sets_env(tmp_path, monkeypatch):
    monkeypatch.delenv("KB_TRACE", raising=False)
    from kb import mcp as mcp_mod
    monkeypatch.setattr(mcp_mod, "build_server",
                        lambda *a, **k: type("S", (), {"run": lambda self, **kw: None})())
    assert mcp_mod.main(["--repo", str(tmp_path), "--trace"]) == 0
    import os
    assert os.environ.get("KB_TRACE") == "1"
