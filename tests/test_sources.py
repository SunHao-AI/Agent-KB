"""FR-6 SourceConnector 契约回归(demo 假源验收, TDBM 未联调只测防御解析)。"""
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from kb import sources
from kb.index import build_indexes
from kb.sources import DemoConnector, Hit, TdbmConnector

from conftest import make_entry

pytestmark = pytest.mark.asyncio


async def _call(server, name, args):
    async with create_connected_server_and_client_session(server) as client:
        res = await client.call_tool(name, args)
        text = res.content[0].text
        return res.isError, (json.loads(text) if text.startswith(("{", "[")) else text)


# ---- 契约基本盘 -----------------------------------------------------------

def test_hit_unified_addressing_and_summary_cap():
    h = Hit.make("demo", "d1", "标题", "长" * 400)
    assert h["id"] == "source://demo/d1" and h["source"] == "demo"
    assert h["summary"].endswith("…[截断]") and len(h["summary"]) <= 310


def test_demo_search_and_get():
    c = DemoConnector()
    hits = c.search("网关", limit=5)
    assert hits and hits[0]["id"] == "source://demo/d1"
    text = c.get("source://demo/d1")
    assert text and "网关超时排查" in text
    assert c.get("source://other/x") is None  # 非本源的 id 不认领
    assert c.health()["ok"] is True


def test_failure_silent_degradation():
    c = DemoConnector(fail=True)
    assert c.search("网关") == []            # 检索主链路绝不抛错
    assert c.health()["ok"] is False
    assert "ConnectionError" in c.health()["error"]


def test_build_default_empty():
    """零风险默认: 不设 KB_SOURCES → 无外接源, 行为与接入前一致。"""
    assert sources.build_connectors(only="") == []


def test_build_tdbm_requires_config(monkeypatch):
    for k in ("KB_TDBM_URL", "KB_TDBM_SERVICE_ID", "KB_TDBM_WIKI_ID"):
        monkeypatch.delenv(k, raising=False)
    assert sources.build_connectors(only="tdbm") == []  # 未配置不启用


# ---- TDBM 防御式解析(不联网, 假响应) --------------------------------------

def test_tdbm_parses_envelope_defensively(monkeypatch):
    c = TdbmConnector(base_url="http://x", service_id="svc", wiki_id="wiki-1")

    def fake_post(path, body):
        assert path == "/wiki/search"
        assert body == {"wiki_id": "wiki-1", "query": "网关", "limit": 5}
        return {"code": 0, "data": {"pages": [
            {"path": "wiki/a.md", "title": "网关超时", "snippet": "BM25 摘要", "score": 3.2}]}}
    monkeypatch.setattr(c, "_post", fake_post)
    hits = c.search("网关", limit=5)
    assert hits[0]["id"] == "source://tdbm/wiki/a.md"
    assert hits[0]["score"] == 3.2

    def fake_post_err(path, body):
        return {"code": 40001, "message": "wiki not found"}
    monkeypatch.setattr(c, "_post", fake_post_err)
    assert c.search("网关") == []  # 业务错误也走静默降级
    assert "40001" in c.health()["error"]


# ---- MCP 联邦集成 ----------------------------------------------------------

@pytest.fixture
def layers(tmp_path):
    proj = tmp_path / "docs"; (proj / "kb").mkdir(parents=True)
    kb = tmp_path / "agentkb"; (kb / "kb").mkdir(parents=True)
    d = proj / "kb" / "pitfall" / "frontend"; d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261014-e1e1", title="Vite HMR 抖动",
                                       status="accepted", confidence="verified")
                            + "\n## 根因\n项目层机制说明文本。\n", encoding="utf-8")
    build_indexes(proj, repo_name="docs")
    return proj, kb


async def test_mcp_federated_search_and_get(layers, monkeypatch):
    proj, kb = layers
    monkeypatch.setenv("KB_SOURCES", "demo")
    from kb.mcp_server import build_server
    srv = build_server(proj, agent_kbs=[kb], repo_name="docs")
    # 本地零命中但 demo 源命中 → 联邦返回 rows+sources
    err, out = await _call(srv, "kb_search", {"query": "网关"})
    assert err is False
    rows = out["rows"] if isinstance(out, dict) else out
    assert any(str(r["id"]).startswith("source://demo/") for r in rows)
    srcs = out["sources"] if isinstance(out, dict) else []
    assert srcs and srcs[0]["source"] == "demo" and srcs[0]["ok"] is True
    # source:// id 可经 kb_get 读全文
    err, text = await _call(srv, "kb_get", {"id": "source://demo/d1"})
    assert err is False and "demo 源全文" in text


async def test_mcp_local_default_no_sources_shape(layers, monkeypatch):
    """默认(无 KB_SOURCES): 返回仍是纯 list, 结构零变化。"""
    monkeypatch.delenv("KB_SOURCES", raising=False)
    proj, kb = layers
    from kb.mcp_server import build_server
    srv = build_server(proj, agent_kbs=[kb], repo_name="docs")
    err, out = await _call(srv, "kb_search", {"query": "Vite"})
    assert err is False and isinstance(out, list)
