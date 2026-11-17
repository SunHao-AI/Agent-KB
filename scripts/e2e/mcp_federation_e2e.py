"""Agent-KB x TencentDB-Agent-Memory 联邦检索端到端联调(MCP 面).

前置: MemoryKnowledge 已起(默认 http://127.0.0.1:8424, /v3), wiki 已 ready,
    wiki_id 在 D:/WorkPlace/.tdbm-e2e-data/wiki_id.txt。
跑法(任意 cwd):  Agent-KB/.venv/Scripts/python.exe scripts/e2e/mcp_federation_e2e.py

断言:
  A1 kb_search 命中态带外接源行(source://tdbm/...), sources 健康 ok
  A2 kb_get 外接源 id 取回全文, 反斜杠 path 已归一(连接器 _get 走 refs)
  A3 本地层命中不受影响(query=uvicorn 双层共存)
  A4 故障静默降级: 坏 URL 下本地命中照常返回, sources[].ok=false, 不抛错
  A5 trace 落盘: search 事件带 ext 分层 hits, caller/trace_id/schema 齐全
"""
import asyncio
import json
import os
import sys
from pathlib import Path

AGENT_KB = Path(r"D:\WorkPlace\Pycharm\Agent-KB")
TDBM = Path(r"D:\WorkPlace\Pycharm\TencentDB-Agent-Memory")
WIKI_ID = Path(r"D:\WorkPlace\.tdbm-e2e-data\wiki_id.txt").read_text(encoding="utf-8").strip()

sys.path.insert(0, str(AGENT_KB / "src"))
from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

PY = str(AGENT_KB / ".venv" / "Scripts" / "python.exe")
FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    tag = "PASS" if cond else "FAIL"
    print(f"[{tag}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


def kb_env(**over: str) -> dict:
    env = dict(os.environ,
               KB_SOURCES="tdbm",
               KB_TDBM_URL="http://127.0.0.1:8424/v3",
               KB_TDBM_SERVICE_ID="default",
               KB_TDBM_WIKI_ID=WIKI_ID,
               KB_TRACE="1",
               PYTHONIOENCODING="utf-8")
    env.update(over)
    return env


def params(**over: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=PY,
        args=["-m", "kb.mcp", "--repo", "docs", "--agent-kb", ".agent-kb",
              "--repo-name", "tencentdb-agent-memory"],
        env=kb_env(**over), cwd=str(TDBM))


async def search(s: ClientSession, query: str, limit: int = 10) -> dict:
    res = await s.call_tool("kb_search", {"query": query, "limit": limit})
    return json.loads(res.content[0].text)


def rows_of(payload: dict) -> list[dict]:
    return payload.get("rows", payload if isinstance(payload, list) else [])


async def main() -> None:
    # ── 正常态: 联邦检索 + 取全文 ────────────────────────────────
    async with stdio_client(params()) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()

            p1 = await search(s, "federated")
            rows1 = rows_of(p1)
            ext1 = [h for h in rows1 if h.get("source") == "tdbm"]
            check("A1a 外接源命中存在", len(ext1) > 0, f"ext={len(ext1)}/{len(rows1)}")
            src_health = p1.get("sources") if isinstance(p1, dict) else None
            check("A1b sources 健康块 ok",
                  bool(src_health) and all(x["ok"] for x in src_health),
                  json.dumps(src_health, ensure_ascii=False) if src_health else "无 sources 块")
            check("A1c 命中 id 已归一化(服务端原样返回含反斜杠 path)",
                  ext1 and all("\\" not in h["id"] for h in ext1),
                  ext1[0]["id"] if ext1 else "")

            # uvicorn 页 BM25 排名进不了 federated 查询, 用本词查并取它做 kb_get 目标
            p3 = await search(s, "uvicorn")
            rows3 = rows_of(p3)
            local3 = [h for h in rows3 if not h["id"].startswith("source://")]
            ext3 = [h for h in rows3 if h["id"].startswith("source://")]
            check("A3 uvicorn 双层共存(本地+外接)",
                  len(local3) > 0 and len(ext3) > 0,
                  f"local={len(local3)} ext={len(ext3)}")
            target = next((h for h in ext3 if "uvicorn" in h["id"].lower()), None)
            check("A1d uvicorn 页经归一化进入外接命中集",
                  target is not None and "\\" not in target["id"],
                  target["id"] if target else "未命中 uvicorn 页")

            if target:
                g = await s.call_tool("kb_get", {"id": target["id"]})
                text = g.content[0].text
                check("A2 外接源 kb_get 全文(ASGI/multiprocessing 均在)",
                      "ASGI" in text and "multiprocessing" in text,
                      f"{len(text)} chars")

    # ── 故障态: 坏 URL 静默降级 ─────────────────────────────────
    async with stdio_client(params(KB_TDBM_URL="http://127.0.0.1:9/v3")) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            p4 = await search(s, "uvicorn")
            rows4 = rows_of(p4)
            bad = [x for x in (p4.get("sources") or []) if not x["ok"]]
            check("A4 坏后端不抛错且本地命中保留, 健康标红",
                  len(rows4) > 0 and len(bad) == 1 and bool(bad[0]["error"]),
                  bad[0]["error"][:80] if bad else "无故障标记")

    # ── trace 落盘核查 ─────────────────────────────────────────
    import datetime as dt
    tf = AGENT_KB / "traces" / f"{dt.date.today():%Y-%m-%d}.jsonl"
    events = []
    if tf.exists():
        for line in tf.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ev.get("caller_repo") == "tencentdb-agent-memory":
                events.append(ev)
    searches = [e for e in events if e.get("kind") == "search" and e.get("ext")]
    gets = [e for e in events if e.get("kind") == "get"
            and str(e.get("id", "")).startswith("source://tdbm/")]
    check("A5a trace search 事件带 ext 分层", len(searches) > 0,
          f"{len(searches)} 条")
    check("A5b trace get 事件读到 source://tdbm/ 条目", len(gets) > 0,
          f"{len(gets)} 条")
    healthy = [e for e in searches
               if any(x.get("ok") and x.get("hits") for x in e["ext"])]
    check("A5c ext.hits 记录外接命中 id(健康态事件)", len(healthy) > 0,
          f"trace_id={healthy[-1]['trace_id']}" if healthy else
          f"仅 {len(searches)} 条 search 事件且 ext.hits 全空(故障态属正常)")

    print("\n== 结果:", "全部通过" if not FAILURES else f"失败 {len(FAILURES)} 项: {FAILURES}")
    sys.exit(0 if not FAILURES else 1)


asyncio.run(main())
