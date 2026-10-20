"""FR-2.4 spider-live 的纯映射回归(不依赖 Node)。"""
from kb.spider_live import event_to_updates, find_spider_home
import pytest


def _search():
    return {"kind": "search", "trace_id": "t1", "caller_repo": "web",
            "query": "vite", "returned": ["p1", "g1", "d1"],
            "layers": [
                {"repo": "docs", "scanned": 5, "rejected": {"filter": 0, "query": 4},
                 "matched": [{"id": "p1", "title": "项目坑", "hit_fields": ["title"]},
                             {"id": "g1", "title": "通用坑", "hit_fields": ["tags"]}],
                 "taken": 2, "truncated_at_limit": False},
            ],
            "ext": [{"source": "demo", "ok": True, "hits": ["d1"]}]}


def test_route_mapping_three_branches():
    cfg, events = event_to_updates(_search())
    by = {e["id"]: e for e in events}
    assert by["p1"]["route"] == "code"   # 首层=项目层(docs) 全部 code 绿
    assert by["g1"]["route"] == "code"
    assert by["d1"]["route"] == "model"  # 外接源 → model 橙
    assert cfg["routes"]["you"]["color"] == "#F0CA57"  # 已读消费=you 黄(由 get 事件驱动)


def test_layers_outcome_first_layer_is_project():
    cfg, events = event_to_updates(_search())
    by = {e["id"]: e for e in events}
    assert by["p1"]["route"] == "code" and by["g1"]["route"] == "code"


def test_two_layers_route_by_layer():
    ev = _search()
    ev["layers"].append({"repo": "kb", "scanned": 3,
                         "rejected": {"filter": 0, "query": 2},
                         "matched": [{"id": "u1", "title": "栈层", "hit_fields": ["summary"]}],
                         "taken": 1, "truncated_at_limit": False})
    ev["returned"].append("u1")
    _, events = event_to_updates(ev)
    by = {e["id"]: e for e in events}
    assert by["u1"]["route"] == "model"          # 第二层(通用层) → model


def test_zero_hit_session_has_subtitle_hint():
    ev = _search()
    ev["returned"], ev["layers"][0]["matched"], ev["ext"] = [], [], []
    cfg, events = event_to_updates(ev)
    assert events == [] and "0 命中" in cfg["subtitle"]


def test_titles_truncated_to_40():
    ev = _search()
    ev["layers"][0]["matched"][0]["title"] = "长" * 60
    _, events = event_to_updates(ev)
    assert len(next(e for e in events if e["id"] == "p1")["label"]) <= 40


def test_find_spider_home_missing_raises(monkeypatch):
    from kb import spider_live
    monkeypatch.setattr(spider_live, "COMMON_HOMES", [])
    with pytest.raises(FileNotFoundError):
        spider_live.find_spider_home(r"Z:\不存在的目录")
