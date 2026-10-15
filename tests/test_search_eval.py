import json
from kb import search


def _mk(tmp_path, recs):
    d = tmp_path / "kb"
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    return tmp_path


def _rec(i, title="nginx 413 body size", tags=("nginx", "upload"),
         summary="客户端 body 超限被 nginx 挡回", **over):
    r = {"id": f"kb-x{i}", "title": title, "type": "pitfall", "domain": ["frontend"],
         "tags": list(tags), "scope": "project", "status": "accepted",
         "confidence": "verified", "summary": summary,
         "path": f"kb/pitfall/frontend/x{i}.md", "updated": "2026-10-12", "repo": "web"}
    r.update(over)
    return r


def test_identity_holds(tmp_path):
    _mk(tmp_path, [_rec(i) for i in range(4)] + [_rec(90, title="vite hmr", tags=("vite",))])
    rows, rep = search.evaluate(tmp_path, query="vite")
    assert rep["scanned"] == 5
    assert rep["rejected"]["filter"] + rep["rejected"]["query"] + len(rep["matched"]) == 5
    assert [m["id"] for m in rep["matched"]] == ["kb-x90"]


def test_filter_rejection_counted(tmp_path):
    _mk(tmp_path, [_rec(1), _rec(2, type="howto")])
    rows, rep = search.evaluate(tmp_path, type="pitfall", query="nginx")
    assert rep["scanned"] == 2
    assert rep["rejected"] == {"filter": 1, "query": 0}
    assert [m["id"] for m in rep["matched"]] == ["kb-x1"]


def test_query_rejection_counted(tmp_path):
    _mk(tmp_path, [_rec(1), _rec(2, title="无关标题", tags=("x",), summary="无关")])
    _, rep = search.evaluate(tmp_path, query="nginx")
    assert rep["rejected"] == {"filter": 0, "query": 1}


def test_hit_fields_and_spans(tmp_path):
    _mk(tmp_path, [_rec(1, title="vite 指南", tags=("vite", "hmr"), summary="无关")])
    _, rep = search.evaluate(tmp_path, query="vite")
    m = rep["matched"][0]
    assert m["hit_fields"] == ["title", "tags"]
    assert m["rank"] == 1
    # hay = "vite 指南 vite hmr 无关"; tags 段起点 = len(title)+1
    start = len("vite 指南") + 1
    assert m["hit_spans"] == [[0, 4], [start, start + 4]]


def test_summary_only_hit(tmp_path):
    _mk(tmp_path, [_rec(1, title="t", tags=("a",), summary="提到了 zzz 一词")])
    _, rep = search.evaluate(tmp_path, query="zzz")
    assert rep["matched"][0]["hit_fields"] == ["summary"]


def test_no_query_all_pass_empty_fields(tmp_path):
    _mk(tmp_path, [_rec(1), _rec(2)])
    rows, rep = search.evaluate(tmp_path)
    assert rep["rejected"] == {"filter": 0, "query": 0}
    assert len(rep["matched"]) == 2
    assert all(m["hit_fields"] == [] and m["hit_spans"] == [] for m in rep["matched"])


def test_search_delegates_and_limit_unchanged(tmp_path):
    _mk(tmp_path, [_rec(i) for i in range(5)])
    limited = search.search(tmp_path, query="nginx", limit=2)
    rows, rep = search.evaluate(tmp_path, query="nginx")
    assert limited == rows[:2]
    assert len(rep["matched"]) == 5
    assert search.search(tmp_path, query="nope") == []


def test_case_insensitive(tmp_path):
    _mk(tmp_path, [_rec(1, title="Vite HMR Guide", tags=(), summary="")])
    _, rep = search.evaluate(tmp_path, query="VITE")
    assert rep["matched"][0]["hit_fields"] == ["title"]


def test_missing_index_returns_empty(tmp_path):
    rows, rep = search.evaluate(tmp_path)
    assert rows == [] and rep == {"scanned": 0,
                                  "rejected": {"filter": 0, "query": 0}, "matched": []}
