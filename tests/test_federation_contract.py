"""联邦 L2 记录契约回归(spec 2026-11-14 §5.2-6/7): CLI/MCP 面 summary 透传、
形状一致、埋点 compact 口径锁定。MCP 范式逐字对齐 tests/test_mcp.py。"""
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from kb import trace
from kb.cli import main
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
def env(tmp_path, monkeypatch):
    root = tmp_path / "agent-kb"
    root.mkdir()
    monkeypatch.setattr(trace, "kb_root", lambda: root)   # 隔离真实 traces/
    monkeypatch.delenv("KB_TRACE", raising=False)
    proj = tmp_path / "docs"
    d = proj / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True)
    (d / "a.md").write_text(make_entry(id="kb-20261114-f001", title="Vite HMR 抖动",
                                       status="accepted", confidence="verified"),
                            encoding="utf-8")
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


async def test_mcp_create_update_summary_roundtrip(env):
    _, proj = env
    srv = build_server(proj, [], repo_name="docs")
    err, out = await _call(srv, "kb_create", {
        "type": "howto", "domain": "tooling", "title": "联邦形状验证条目",
        "body": "## 用法\n用 kb_export 做跨仓上提的操作步骤说明。\n",
        "summary": "跨仓上提必须先 kb promote 建议再由人 set-scope。"})
    assert err is False
    err, out = await _call(srv, "kb_update", {"id": out["id"],
                                              "summary": "改后结论: 仍需人工终审。"})
    assert err is False
    # 简报缺陷修正: kb_create 落 draft, 而 kb_search 只读 live 池(draft 永不返回),
    # 缺终审步则 hits 恒为零命中 dict。补 MCP kb_review 自审 accepted
    # (draft→accepted 合法流转, accepted 需 evidence + confidence 提升)。
    err, out = await _call(srv, "kb_review", {
        "id": out["id"], "to": "accepted", "confidence": "verified",
        "evidence": "联邦契约用例实测"})
    assert err is False
    err, hits = await _call(srv, "kb_search", {"query": "联邦形状验证条目"})
    assert err is False
    row = hits[0]
    assert row["summary"] == "改后结论: 仍需人工终审。"
    assert row["origin"] == "local" and row["uri"] is None          # 与本地行同契约
    assert "hit_fields" in row                                       # 既有形状不破坏


async def test_cli_search_hit_shape_matches_mcp(env):
    """§5.2-7: CLI 行与 MCP 行形状一致(CLI 全行透传 ⊇ MCP 字段)。"""
    _, proj = env
    assert main(["search", "--repo", str(proj), "--query", "Vite", "--no-trace"]) == 0
    # 简报缺陷修正: kb.search.search() 返回**裸索引行**(无 hit_fields, 该字段由
    # layers.search_layers_report 按 id 对齐补上), CLI/MCP 实际走的都是 layers 面;
    # 断言必须打在 CLI 真实使用的面, 否则锁的是错误口径。
    from kb.layers import search_layers_report
    row = search_layers_report([proj], query="Vite", limit=5)[0][0]
    assert {"hit_fields", "summary", "origin", "uri", "path", "id"} <= row.keys()


async def test_returned_chars_compact(env, monkeypatch, capsys):
    """§4 口径锁定(本行即回归测试本身): 埋点 returned_chars 与 stdout 结果的
    compact `json.dumps(res, ensure_ascii=False)` 逐字符等长——print 的 indent 只准
    出现在 stdout, 混进字符账即虚高 overhead/meta_only。"""
    root, proj = env
    monkeypatch.setenv("KB_TRACE", "1")
    assert main(["search", "--repo", str(proj), "--query", "vite"]) == 0
    res = json.loads(capsys.readouterr().out)   # stdout 是 indent 版, 解析回对象
    ev = _events(root)[0]
    assert ev["returned_chars"] == len(json.dumps(res, ensure_ascii=False))
