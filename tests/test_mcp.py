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
    # FR-4.1: 命中行透传 hit_fields; compact 序列化无缩进换行
    assert out[0]["hit_fields"] == ["title"]


async def test_search_zero_hit_returns_hint_not_bare_list(layers):
    """FR-3.2: 零命中返回 {hits, hint, suggest} 而非裸 []。"""
    proj, kb = layers
    srv = build_server(proj, agent_kbs=[kb], repo_name="docs")
    err, out = await _call(srv, "kb_search", {"query": "vitee"})
    assert err is False
    assert out["hits"] == [] and "scanned" in out["hint"]
    assert "vite" in out["suggest"]


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


# --- kb_review: agent 自审终审(保守放开: 仅状态流转, scope 仍人工) ---

async def _create(srv, title):
    """body 内嵌唯一 title, 避免多条 create 因指纹相同被查重拒建."""
    body = (f"## 根因\n{title}: Redis 连接池默认上限过低, "
            f"高并发下请求排队超时, 调大后恢复。\n")
    err, out = await _call(srv, "kb_create", {
        "type": "pitfall", "domain": "backend", "title": title, "body": body})
    assert err is False, out
    return out["id"]


async def test_review_agent_accept_with_evidence(layers):
    proj, _ = layers
    srv = build_server(proj, repo_name="docs")
    eid = await _create(srv, "Redis 连接池耗尽 独立验证")
    err, out = await _call(srv, "kb_review", {
        "id": eid, "to": "accepted", "confidence": "verified",
        "evidence": "压测复现: pool=10 时 p99>5s, 调至 50 后恢复"})
    assert err is False
    assert out["status"] == "accepted" and out["confidence"] == "verified"
    assert "auto-reviewed" in out["tags"] and out["verified_by"] == "agent"
    assert out["verification"]["evidence"].startswith("压测复现")


async def test_review_accept_without_evidence_blocked(layers):
    proj, _ = layers
    srv = build_server(proj, repo_name="docs")
    eid = await _create(srv, "Redis 慢查询 独立验证二")
    err, out = await _call(srv, "kb_review", {"id": eid, "to": "accepted"})
    assert err is True and "speculative" in out


async def test_review_accept_evidence_without_confidence_blocked(layers):
    proj, _ = layers
    srv = build_server(proj, repo_name="docs")
    eid = await _create(srv, "Redis 慢查询 独立验证三")
    err, out = await _call(srv, "kb_review", {
        "id": eid, "to": "accepted", "evidence": "有证据但不提升 confidence"})
    assert err is True and "speculative" in out


async def test_review_illegal_to(layers):
    proj, _ = layers
    srv = build_server(proj, repo_name="docs")
    eid = await _create(srv, "Redis 慢查询 独立验证四")
    err, out = await _call(srv, "kb_review", {"id": eid, "to": "stack"})
    assert err is True


async def test_review_session_cap_three(layers):
    proj, _ = layers
    srv = build_server(proj, repo_name="docs")  # 每 server 实例即一次 agent 会话
    ok_ids = [await _create(srv, f"Redis 池耗尽 独立验证{i}") for i in range(3)]
    for eid in ok_ids:
        err, _ = await _call(srv, "kb_review", {
            "id": eid, "to": "accepted", "confidence": "verified",
            "evidence": "实测复现并通过"})
        assert err is False
    fourth = await _create(srv, "Redis 池耗尽 独立验证9")
    err, out = await _call(srv, "kb_review", {
        "id": fourth, "to": "accepted", "confidence": "verified",
        "evidence": "实测复现并通过"})
    assert err is True and "上限" in out


async def test_review_proposed_needs_no_evidence(layers):
    proj, _ = layers
    srv = build_server(proj, repo_name="docs")
    eid = await _create(srv, "Redis 慢日志 独立验证五")
    err, out = await _call(srv, "kb_review", {"id": eid, "to": "proposed"})
    assert err is False and out["status"] == "proposed"
    err, out = await _call(srv, "kb_review", {
        "id": eid, "to": "accepted", "confidence": "probable",
        "evidence": "两处项目实测一致"})
    assert err is False and out["status"] == "accepted"
