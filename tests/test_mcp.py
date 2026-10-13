import json
import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from kb.index import build_indexes
from kb.mcp_server import build_server
from conftest import make_entry

pytestmark = pytest.mark.asyncio


async def _call(server, name, args):
    async with create_connected_server_and_client_session(server) as client:
        res = await client.call_tool(name, args)
        text = res.content[0].text
        return res.isError, (json.loads(text) if text.startswith(("{", "[")) else text)


@pytest.fixture
def layers(tmp_path):
    proj = tmp_path / "docs"; (proj / "kb").mkdir(parents=True)
    kb = tmp_path / "agentkb"; (kb / "kb").mkdir(parents=True)
    d = proj / "kb" / "pitfall" / "frontend"; d.mkdir(parents=True)
    # title 含"换个说法" token: 短根因文本(规范化<16)触发 gate 短源门槛跳过指纹查重,
    # 查重只能走 title token 路径, 否则 duplicate 用例永不命中(见 task-9-report)
    (d / "a.md").write_text(make_entry(id="kb-20261014-e1e1", title="Vite HMR 抖动 换个说法",
                                       status="accepted", confidence="verified")
                            + "\n## 根因\n项目层机制说明文本。\n", encoding="utf-8")
    build_indexes(proj, repo_name="docs")
    return proj, kb


async def test_search_merges_layers(layers, tmp_path):
    proj, kb = layers
    srv = build_server(proj, agent_kbs=[kb], repo_name="docs")
    err, out = await _call(srv, "kb_search", {"query": "Vite"})
    assert err is False and out[0]["id"] == "kb-20261014-e1e1"


async def test_get_returns_full_text(layers):
    proj, kb = layers
    srv = build_server(proj, agent_kbs=[kb], repo_name="docs")
    err, out = await _call(srv, "kb_get", {"id": "kb-20261014-e1e1"})
    assert "## 根因" in out


async def test_get_not_found(layers):
    proj, kb = layers
    srv = build_server(proj, agent_kbs=[kb], repo_name="docs")
    err, out = await _call(srv, "kb_get", {"id": "kb-20261014-0000"})
    assert err is True and "not found" in out


async def test_create_draft_ok(layers):
    proj, kb = layers
    srv = build_server(proj, agent_kbs=[kb], repo_name="docs")
    err, out = await _call(srv, "kb_create", {
        "type": "pitfall", "domain": "frontend", "title": "新沉淀",
        "body": "## 根因\n全新机制说明文本内容。\n"})
    assert err is False and out["status"] == "draft" and out["scope"] == "project"


async def test_create_duplicate_rejected(layers):
    proj, kb = layers
    srv = build_server(proj, agent_kbs=[kb], repo_name="docs")
    err, out = await _call(srv, "kb_create", {
        "type": "pitfall", "domain": "frontend", "title": "换个说法",
        "body": "## 根因\n项目层机制说明文本。\n"})
    assert err is True and "kb-20261014-e1e1" in out


async def test_update_non_draft_rejected(layers):
    proj, kb = layers
    srv = build_server(proj, agent_kbs=[kb], repo_name="docs")
    err, out = await _call(srv, "kb_update", {"id": "kb-20261014-e1e1", "body": "x"})
    assert err is True and "only draft" in out
