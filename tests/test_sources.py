"""FR-6 SourceConnector 契约回归(demo 假源验收; TDBM 按真机联调 schema 回归)。"""
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


def test_build_tokens_exact_not_substring():
    """§51 实锤: 旧 `"demo" in wanted` 子串匹配, KB_SOURCES=notdemo(明确想排除)
    反而意外启用 demo——外接源内容会混进 agent 检索结果, 开关必须精确。"""
    assert sources.build_connectors(only="notdemo") == []
    assert sources.build_connectors(only="nodemo_nowiki") == []
    # 正例不回退: 大小写不敏感、空白容忍、未知 token 忽略(前向兼容)
    assert [c.name for c in sources.build_connectors(only="DEMO")] == ["demo"]
    assert [c.name for c in sources.build_connectors(only=" demo , tdbm ")] == ["demo"]
    assert [c.name for c in sources.build_connectors(only="futurex,demo")] == ["demo"]


def test_search_limit_contract():
    """§51: 契约"条数≤limit"。旧实现 limit≤0 被 max(1,…) 抬成 1 再被 [:limit]
    截空——语义拧巴且对远程连接器白打一次网络。修复后 ≤0 直接零命中不触后端。"""
    calls = []

    class Counting(DemoConnector):
        def _search(self, query, limit):
            calls.append(limit)
            return super()._search(query, limit)

    c = Counting()
    assert c.search("网关", limit=0) == [] and not calls   # 不触后端
    assert c.search("网关", limit=-1) == [] and not calls
    assert len(c.search("网关", limit=1)) == 1
    assert c.search("网关", limit="abc")            # 非数值回退默认 5, 不炸
    assert len(c.search("网关", limit=99)) == len(c.search("网关", limit=20))


# ---- TDBM 解析(不联网, 响应为 2026-10-20 真机联调核实过的真实 schema) ----

def test_tdbm_search_real_schema(monkeypatch):
    c = TdbmConnector(base_url="http://x", service_id="svc", wiki_id="wiki-1")

    def fake_post(path, body):
        assert path == "/wiki/search"
        assert body == {"wiki_id": "wiki-1", "query": "网关", "limit": 5}
        # 真机形状: data.results(list of {path,title,snippet,score,type});
        # links 也是 list, 解析器必须显式取 results 而非首个 list
        return {"code": 0, "data": {"results": [
            {"path": "wiki/entities\\redis-timeout.md",  # Windows 真机混用分隔符
             "title": "Redis Timeout", "snippet": "BM25 摘要", "score": 3.2,
             "type": "entity"}], "links": [], "count": 1}}
    monkeypatch.setattr(c, "_post", fake_post)
    hits = c.search("网关", limit=5)
    assert hits[0]["id"] == "source://tdbm/wiki/entities/redis-timeout.md"  # 已归一化
    assert hits[0]["score"] == 3.2

    def fake_post_err(path, body):
        return {"code": 40001, "message": "wiki not found"}
    monkeypatch.setattr(c, "_post", fake_post_err)
    assert c.search("网关") == []  # 业务错误也走静默降级
    assert "40001" in c.health()["error"]


def test_tdbm_get_uses_refs_and_ref_fields(monkeypatch):
    c = TdbmConnector(base_url="http://x", service_id="svc", wiki_id="wiki-1")

    def fake_post(path, body):
        # 真机契约: 请求字段是 refs(非 paths), 响应 items 匹配字段是 ref(非 path)
        assert path == "/wiki/page/read"
        assert body == {"wiki_id": "wiki-1", "refs": ["wiki/entities/redis-timeout.md"]}
        return {"code": 0, "data": {"items": [
            {"ref": "wiki/entities/redis-timeout.md", "content": "---\ntype: entity\n---\n正文"}]}}
    monkeypatch.setattr(c, "_post", fake_post)
    text = c.get("source://tdbm/wiki/entities/redis-timeout.md")
    assert text and "正文" in text

    def fake_post_missing(path, body):
        return {"code": 0, "data": {"items": [
            {"ref": "wiki/entities/redis-timeout.md", "not_found": True}]}}
    monkeypatch.setattr(c, "_post", fake_post_missing)
    assert c.get("source://tdbm/wiki/entities/redis-timeout.md") is None


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
