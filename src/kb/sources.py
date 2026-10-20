"""SourceConnector 契约(PRD FR-6.2) — 外接知识源统一只读接入层。

契约(冻结要点):
- search(query, limit) → list[Hit]: 摘要先行, Hit 必带 {id, title, summary,
  source, score}; id 用 `source://<connector>/<原生id>` 统一寻址;
- get(id) → 全文 str | None;
- 三重预算闸门(借 TDBM 自身设计): 条数≤limit、正文≤max_chars、超时≤timeout_sec,
  超限截断并在 Hit.summary 尾部标注 …[截断];
- 故障静默降级: 任何异常 → [] + health.error 记录, 检索主链路绝不抛错;
- 凭据只从环境/用户级配置读, 永不写入 trace 与 git。

内置连接器: demo(内存假源, 验收联邦检索用) / tdbm(TencentDB-Agent-Memory
LLM-Wiki BM25 OpenAPI)。Notion/飞书/图数据库为 P2, 按本契约追加文件即可。
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

SUMMARY_CAP = 300  # 摘要先行: 返回给 agent 的 summary 硬上限(字符)


class Hit(dict):
    """检索命中(与本地 index 行同构的最小集 + source 字段)。"""

    @classmethod
    def make(cls, connector: str, native_id: str, title: str, summary: str,
             score: float = 1.0, **extra) -> "Hit":
        s = str(summary or "").replace("\n", " ")
        clipped = len(s) > SUMMARY_CAP
        return cls(id=f"source://{connector}/{native_id}", native_id=native_id,
                   title=str(title or native_id)[:200],
                   summary=(s[:SUMMARY_CAP] + "…[截断]") if clipped else s,
                   source=connector, score=score, path=None, **extra)


class SourceConnector:
    """连接器基类。子类只需实现 _search/_get; 预算与降级在基类兜底。"""

    name = "?"
    timeout_sec = 2.0
    max_chars = 8000

    def __init__(self, **cfg):
        self.cfg = cfg
        self.last_error: str | None = None

    def search(self, query: str, limit: int = 5) -> list[Hit]:
        try:
            hits = self._search(query, max(1, min(limit, 20)))
            return [h for h in hits if isinstance(h, Hit)][:limit]
        except Exception as exc:  # 红线: 故障静默降级, 记健康不抛出
            self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            return []

    def get(self, id: str) -> str | None:
        if not id.startswith(f"source://{self.name}/"):
            return None
        try:
            text = self._get(id[len(f"source://{self.name}/"):])
            if text is None:
                return None
            return text[: self.max_chars]
        except Exception as exc:
            self.last_error = f"{type(exc).__name__}: {exc}"[:200]
            return None

    def health(self) -> dict:
        return {"source": self.name, "ok": self.last_error is None,
                "error": self.last_error}

    def _search(self, query: str, limit: int) -> list[Hit]:
        raise NotImplementedError

    def _get(self, native_id: str) -> str | None:
        raise NotImplementedError


class DemoConnector(SourceConnector):
    """内存假源: 无网络验收联邦检索/蜘蛛第四路由; 数据由构造方注入。"""

    name = "demo"

    def __init__(self, docs: list[dict] | None = None, fail: bool = False, **cfg):
        super().__init__(**cfg)
        # docs: [{native_id, title, summary}]
        self.docs = docs or [
            {"native_id": "d1", "title": "示例: 网关超时排查", "summary": "外接 demo 源条目, 用于验收联邦检索与蜘蛛动画第四路由。"},
            {"native_id": "d2", "title": "示例: 缓存一致性", "summary": "demo 源第二条目, 含 网关 关键词。"},
        ]
        self._fail = fail

    def _search(self, query: str, limit: int) -> list[Hit]:
        if self._fail:
            raise ConnectionError("demo 源故意故障(验证静默降级)")
        toks = query.lower().split()
        out = []
        for d in self.docs:
            hay = (d["title"] + " " + d["summary"]).lower()
            if all(t in hay for t in toks):
                out.append(Hit.make(self.name, d["native_id"], d["title"],
                                    d["summary"], score=1.0))
        return out[:limit]

    def _get(self, native_id: str) -> str | None:
        d = next((x for x in self.docs if x["native_id"] == native_id), None)
        return f"# {d['title']}\n\n{d['summary']}\n(demo 源全文, 无门禁)" if d else None


class TdbmConnector(SourceConnector):
    """TencentDB-Agent-Memory LLM-Wiki BM25 检索(FR-6.3 默认外接源)。

    契约核实自其仓内 MemoryKnowledge/openapi.yaml: POST /wiki/search,
    租户头 x-tdai-service-id, body {wiki_id, query, limit}, 响应为
    ApiResponseEnvelope(code=0 + data)。⚠ 未经真实实例联调(挂账):
    data 内页列表字段名做了宽容取首个 list 的防御式解析。
    """

    name = "tdbm"

    def __init__(self, base_url: str | None = None, service_id: str | None = None,
                 wiki_id: str | None = None, api_key: str | None = None, **cfg):
        super().__init__(**cfg)
        # 凭据只从环境读(FR-6.2 红线), 构造参数仅用于测试注入
        import os
        self.base = (base_url or os.environ.get("KB_TDBM_URL", "")).rstrip("/")
        self.service_id = service_id or os.environ.get("KB_TDBM_SERVICE_ID", "")
        self.wiki_id = wiki_id or os.environ.get("KB_TDBM_WIKI_ID", "")
        self.api_key = api_key or os.environ.get("KB_TDBM_API_KEY", "")

    def configured(self) -> bool:
        return bool(self.base and self.service_id and self.wiki_id)

    def _post(self, path: str, body: dict) -> dict:
        headers = {"Content-Type": "application/json",
                   "x-tdai-service-id": self.service_id}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(self.base + path,
                                     data=json.dumps(body).encode(),
                                     headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout_sec) as r:
            return json.loads(r.read().decode("utf-8"))

    def _search(self, query: str, limit: int) -> list[Hit]:
        if not self.configured():
            raise RuntimeError("TDBM 未配置(KB_TDBM_URL/SERVICE_ID/WIKI_ID)")
        resp = self._post("/wiki/search",
                          {"wiki_id": self.wiki_id, "query": query, "limit": limit})
        if resp.get("code") not in (0, None):
            raise RuntimeError(f"TDBM code={resp.get('code')} msg={resp.get('message')}")
        data = resp.get("data") or {}
        rows = data if isinstance(data, list) else next(
            (v for v in data.values() if isinstance(v, list)), [])
        out = []
        for it in rows[:limit]:
            if not isinstance(it, dict):
                continue
            nid = str(it.get("path") or it.get("page_id") or it.get("id") or "")
            out.append(Hit.make(self.name, nid,
                                str(it.get("title") or it.get("name") or nid),
                                str(it.get("snippet") or it.get("summary")
                                    or it.get("excerpt") or ""),
                                score=float(it.get("score") or 1.0)))
        return out

    def _get(self, native_id: str) -> str | None:
        resp = self._post("/wiki/page/read",
                          {"wiki_id": self.wiki_id, "paths": [native_id]})
        data = resp.get("data") or {}
        rows = data if isinstance(data, list) else next(
            (v for v in data.values() if isinstance(v, list)), [])
        for it in rows:
            if isinstance(it, dict) and str(it.get("path") or "") == native_id:
                return str(it.get("content") or "")
        return None


def build_connectors(only: str | None = None) -> list[SourceConnector]:
    """按配置装配启用源。KB_SOURCES=demo|tdbm|demo,tdbm(默认 demo 关闭)。

    默认空列表 = 纯本地(与接入前行为完全一致, 零风险默认)。
    """
    import os
    wanted = (only or os.environ.get("KB_SOURCES", "")).lower()
    out: list[SourceConnector] = []
    if "demo" in wanted:
        out.append(DemoConnector())
    if "tdbm" in wanted:
        c = TdbmConnector()
        if c.configured():
            out.append(c)
    return out
