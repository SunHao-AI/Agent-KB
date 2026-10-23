from kb.index import build_indexes
from kb.layers import search_layers, search_layers_report, get_layered, related_layers
from conftest import make_entry


def _mk(repo, eid, title, *, status="accepted", related=None, root=None):
    d = repo / "kb" / "pitfall" / "frontend"
    d.mkdir(parents=True, exist_ok=True)
    body = make_entry(id=eid, title=title, status=status, confidence="verified",
                      related=related or [])
    if root:
        body += f"\n## 根因\n{root}\n"
    (d / f"{eid}.md").write_text(body, encoding="utf-8")


def _repo(tmp_path, name, ids_titles):
    r = tmp_path / name
    (r / "kb").mkdir(parents=True)
    for eid, title in ids_titles:
        _mk(r, eid, title, root=f"{name} 的机制说明文本内容 {eid}")
    build_indexes(r, repo_name=name)
    return r


def test_project_layer_first(tmp_path):
    proj = _repo(tmp_path, "docs", [("kb-20261014-1111", "项目层命中")])
    kb = _repo(tmp_path, "agentkb", [("kb-20261014-2222", "通用层命中")])
    res = search_layers([proj, kb], query="命中")
    assert [r["repo"] for r in res] == ["docs", "agentkb"]


def test_same_id_project_wins(tmp_path):
    proj = _repo(tmp_path, "docs", [("kb-20261014-3333", "同 id 项目")])
    kb = _repo(tmp_path, "agentkb", [("kb-20261014-3333", "同 id 通用")])
    text, layer = get_layered([proj, kb], "kb-20261014-3333")
    assert layer == "docs" and "同 id 项目" in text


def test_limit_truncates_across_layers(tmp_path):
    proj = _repo(tmp_path, "docs", [(f"kb-20261014-4{i:02d}", f"甲{i}") for i in range(5)])
    kb = _repo(tmp_path, "agentkb", [(f"kb-20261014-5{i:02d}", f"甲{i}") for i in range(5)])
    assert len(search_layers([proj, kb], query="甲", limit=3)) == 3


def test_limit_contract_nonpositive_and_nonnumeric(tmp_path):
    """§56(第三十八轮): limit 契约归一——limit≤0 截零且不扫库(report 全零,
    MCP 才不会产出"死于过滤器 0/词匹配 0"的自相矛盾 hint); 非数值回退默认。
    JSONSchema 的 int 不拒负数、JSON 允许小数, 校验层拦不住, 必须在漏斗处归一。"""
    proj = _repo(tmp_path, "docs", [(f"kb-20261014-4{i:02d}", f"甲{i}") for i in range(5)])
    kb = _repo(tmp_path, "agentkb", [(f"kb-20261014-5{i:02d}", f"甲{i}") for i in range(5)])
    for bad in (0, -3):
        rows, reports = search_layers_report([proj, kb], query="甲", limit=bad)
        assert rows == []
        assert all(r["scanned"] == 0 and r["matched"] == [] for r in reports)
    rows, _ = search_layers_report([proj, kb], query="甲", limit="3")
    assert len(rows) == 3  # 数字字符串容忍(int() 语义)
    rows, _ = search_layers_report([proj, kb], query="甲", limit="abc")
    assert len(rows) == 10  # 非数值回退默认 10(proj 5 + kb 5 全取)



def test_missing_returns_none(tmp_path):
    proj = _repo(tmp_path, "docs", [("kb-20261014-6666", "有")])
    assert get_layered([proj], "kb-20261014-0000") is None


def test_related_merges_layers(tmp_path):
    proj = _repo(tmp_path, "docs", [("kb-20261014-7777", "项目引用方", )])
    kb = _repo(tmp_path, "agentkb", [])
    _mk(kb, "kb-20261014-8888", "通用被引用", related=["kb-20261014-7777"], root="通用层机制文本")
    build_indexes(kb, repo_name="agentkb")
    out = related_layers([proj, kb], "kb-20261014-7777")
    assert [r["id"] for r in out] == ["kb-20261014-8888"]
