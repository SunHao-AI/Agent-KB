"""kb trace snapshot 端到端: 落盘+周报 / 幂等退 1 / --force / json 格式 / 默认上一周。"""
import datetime as dt
import json

import pytest

from kb import metrics
from kb import trace
from kb.cli import main


@pytest.fixture
def env(tmp_path, monkeypatch):
    """有账本的仓根: 2026-W45 周内 2 检索(1 命中 1 零命中)+ 1 消费。"""
    root = tmp_path / "agent-kb"
    root.mkdir()
    monkeypatch.setattr(trace, "kb_root", lambda: root)
    at = lambda n: (dt.date.fromisocalendar(2026, 45, 1)
                    + dt.timedelta(days=n)).isoformat() + "T10:00:00+08:00"
    for ev in [
        {"kind": "search", "trace_id": "t-4501", "ts": at(0), "source": "cli",
         "caller_repo": "alpha", "query": "vite hmr", "duration_ms": 10,
         "returned": ["kb-1"],
         "layers": [{"repo": "kb", "scanned": 120,
                     "rejected": {"filter": 0, "query": 119},
                     "matched": [{"id": "kb-1", "title": "T1"}],
                     "taken": 1, "truncated_at_limit": False}]},
        {"kind": "get", "trace_id": "t-4501", "ts": at(0), "id": "kb-1",
         "caller_repo": "alpha", "status": "ok", "chars": 900},
        {"kind": "search", "trace_id": "t-4502", "ts": at(1), "source": "mcp",
         "caller_repo": "beta", "query": "rtmp 断流", "duration_ms": 20,
         "returned": [],
         "layers": [{"repo": "kb", "scanned": 120,
                     "rejected": {"filter": 0, "query": 120}, "matched": [],
                     "taken": 0, "truncated_at_limit": False}]}]:
        trace.append_event(ev, root=root)
    return root


def test_snapshot_writes_and_reports(env, capsys):
    assert main(["trace", "snapshot", "--week", "2026-W45"]) == 0
    p = env / "traces" / "metrics" / "2026-W45.json"
    assert p.exists()
    snap = json.loads(p.read_text(encoding="utf-8"))
    assert snap["schema"] == 1 and snap["since"] == "2026-11-02"
    assert snap["metrics"]["searches"] == 2
    out = capsys.readouterr().out
    assert "知识库周指标 · 2026-W45" in out
    assert "消化工单" in out and "rtmp 断流" in out     # 未消化零命中进工单
    assert "上周快照缺失" in out                        # 无上周快照 → 环比显式标注


def test_snapshot_idempotent_refuses_and_force(env, capsys):
    assert main(["trace", "snapshot", "--week", "2026-W45"]) == 0
    capsys.readouterr()
    assert main(["trace", "snapshot", "--week", "2026-W45"]) == 1   # 幂等红线: 退 1
    assert "--force" in capsys.readouterr().err
    assert main(["trace", "snapshot", "--week", "2026-W45", "--force"]) == 0
    assert main(["trace", "snapshot", "--week", "2026-W01"]) == 0   # 空周也成立
    snap = json.loads((env / "traces" / "metrics" / "2026-W01.json")
                      .read_text(encoding="utf-8"))
    assert snap["metrics"]["searches"] == 0            # 空周如实出零, 不报错


def test_snapshot_json_format(env, capsys):
    assert main(["trace", "snapshot", "--week", "2026-W45",
                 "--format", "json"]) == 0
    payload = json.loads(capsys.readouterr().out)      # stdout 必须是纯 JSON
    assert payload["schema"] == 1 and payload["week"] == "2026-W45"


def test_snapshot_bad_week_rejected_by_argparse(env):
    with pytest.raises(SystemExit):                    # 入口即拒, 不进业务面
        main(["trace", "snapshot", "--week", "2026-45"])


def test_snapshot_default_is_previous_iso_week(env, capsys, monkeypatch):
    # 默认周钉死为 W45(账本数据全在 W45): 不依赖用例运行日期。
    # 只测"默认周接线正确"(不传 --week → 用 prev_week 的返回值);
    # prev_week 自身的 ISO 算术由 test_metrics.py 独立覆盖。
    monkeypatch.setattr(metrics, "prev_week", lambda: "2026-W45")
    assert main(["trace", "snapshot"]) == 0
    assert (env / "traces" / "metrics" / "2026-W45.json").exists()
    assert "2026-W45" in capsys.readouterr().out
