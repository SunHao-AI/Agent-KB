import json

from kb import layers, search, trace


def _mk(root, name, recs):
    d = root / name / "kb"
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs), encoding="utf-8")
    return root / name


def _rec(i, title, scope="project", **over):
    r = {"id": f"kb-{i}", "title": title, "type": "pitfall", "domain": ["frontend"],
         "tags": [], "scope": scope, "status": "accepted", "confidence": "verified",
         "summary": "s", "path": "kb/pitfall/frontend/x.md", "updated": "2026-10-12",
         "repo": "web"}
    r.update(over)
    return r


def test_report_shape_and_truncation(tmp_path):
    docs = _mk(tmp_path, "docs", [_rec(i, f"vite {i}") for i in range(3)])
    kb = _mk(tmp_path, "kb", [_rec(i, f"vite k{i}", scope="stack") for i in range(4)])
    rows, reports = layers.search_layers_report([docs, kb], query="vite", limit=4)
    assert len(rows) == 4
    assert [r["repo"] for r in reports] == ["docs", "kb"]
    assert reports[0]["taken"] == 3 and reports[0]["truncated_at_limit"] is False
    assert reports[1]["taken"] == 1 and reports[1]["truncated_at_limit"] is True
    assert reports[1]["scanned"] == 4
    assert reports[1]["rejected"] == {"filter": 0, "query": 0}
    assert [m["rank"] for m in reports[1]["matched"]] == [1, 2, 3, 4]


def test_search_layers_still_equal_layerwise_concat(tmp_path):
    docs = _mk(tmp_path, "docs", [_rec(i, f"vite {i}") for i in range(3)])
    kb = _mk(tmp_path, "kb", [_rec(i, f"vite k{i}", scope="stack") for i in range(4)])
    a = layers.search_layers([docs, kb], query="vite", limit=4)
    b = search.search(docs, query="vite", limit=4) + search.search(kb, query="vite", limit=4)
    assert a == b[:4]


def test_single_layer_zero_matches(tmp_path):
    docs = _mk(tmp_path, "docs", [_rec(1, "a", type="howto"), _rec(2, "b")])
    rows, reports = layers.search_layers_report([docs], query="vite", type="pitfall")
    rep = reports[0]
    assert rep["scanned"] == 2
    assert rep["rejected"] == {"filter": 1, "query": 1}
    assert rep["matched"] == [] and rows == [] and rep["taken"] == 0


def test_build_search_event_shape(tmp_path):
    docs = _mk(tmp_path, "docs", [_rec(1, "vite x")])
    _, rep = search.evaluate(docs, query="vite")
    rep.update({"repo": "docs", "taken": 1, "truncated_at_limit": False})
    ev = trace.build_search_event(
        trace_id="t-1", source="mcp", caller_repo="flysee_video_web", query="vite",
        filters={"type": "pitfall", "domain": None, "tag": None, "scope": None,
                 "status": None, "confidence": None},
        limit=10, reports=[rep], returned=["kb-1"], duration_ms=7)
    assert ev["kind"] == "search" and ev["trace_id"] == "t-1"
    assert ev["source"] == "mcp" and ev["caller_repo"] == "flysee_video_web"
    assert ev["returned"] == ["kb-1"] and ev["duration_ms"] == 7
    assert set(ev["filters"]) == {"type", "domain", "tag", "scope", "status", "confidence"}
    assert len(ev["layers"]) == 1
    assert set(ev["layers"][0]) == {"repo", "scanned", "rejected", "matched",
                                    "taken", "truncated_at_limit"}
    assert ev["layers"][0]["matched"][0]["hit_fields"] == ["title"]
    assert ev["ts"][:4].isdigit()


def test_build_get_event():
    ev = trace.build_get_event(trace_id="t-1", source="mcp", caller_repo="web",
                               id="kb-1", layer="docs", ok=True)
    assert ev["kind"] == "get" and ev["id"] == "kb-1"
    assert ev["layer"] == "docs" and ev["ok"] is True and ev["trace_id"] == "t-1"
