// OpenAI-compatible mock used only for local 联调 of KB -> TencentDB-Agent-Memory.
// Wiki ingest calls /chat/completions twice per source (analysis then generate)
// plus optional merge/overview; every non-generate call may return plain text.
// The generate call must return FILE blocks or ingest throws "no files generated".
const http = require("node:http");

const PORT = Number(process.env.MOCK_LLM_PORT || 8899);

const WIKI_PAGES = [
  {
    path: "wiki/entities/uvicorn.md",
    body: `---
type: entity
title: Uvicorn
sources:
  - kb-integration.md
---

Uvicorn 是 ASGI 服务器, 用于跑 kb serve 这类 Python 异步 HTTP 服务。
联调用例: uvicorn 端口被 multiprocessing 孤儿进程占用时, 只信 netstat 与 curl 复核。`,
  },
  {
    path: "wiki/entities/wiki-service.md",
    body: `---
type: entity
title: MemoryKnowledge wiki-service
sources:
  - kb-integration.md
---

MemoryKnowledge 的 wiki-service 负责 wiki 行的增删改查与 BM25 检索。
/wiki/search 仅在行 status=ready 时返回结果, 否则空列表。`,
  },
  {
    path: "wiki/concepts/federated-search.md",
    body: `---
type: concept
title: Federated search
sources:
  - kb-integration.md
---

联邦检索: kb search 先查本地层, 剩余名额给外接源连接器; 连接器故障静默降级为空。
外接源命中 id 形如 source://tdbm/<原生 path>。`,
  },
];

function generateOutput() {
  return WIKI_PAGES.map(
    (p) => `<<<FILE path="${p.path}">>>\n${p.body}\n<<<END>>>`,
  ).join("\n\n");
}

// Only the generate system prompt carries the "<<<FILE" boundary-marker
// instruction; analysis/merge/overview calls fall through to plain prose.
function textFor(prompt) {
  if (prompt.includes("<<<FILE")) return generateOutput();
  return "Mock analysis: 3 pages (uvicorn, wiki-service, federated-search) worth extracting.";
}

const server = http.createServer((req, res) => {
  if (req.method !== "POST") {
    res.writeHead(405).end("method not allowed");
    return;
  }
  let raw = "";
  req.on("data", (c) => (raw += c));
  req.on("end", () => {
    let body = {};
    try {
      body = JSON.parse(raw || "{}");
    } catch {
      /* keep defaults */
    }
    const messages = Array.isArray(body.messages) ? body.messages : [];
    const prompt = messages.map((m) => m.content).join("\n");
    const text = textFor(prompt);
    const model = body.model || "Memory-Model";
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(
      JSON.stringify({
        id: "chatcmpl-mock",
        object: "chat.completion",
        created: Math.floor(Date.now() / 1000),
        model,
        choices: [
          {
            index: 0,
            message: { role: "assistant", content: text },
            finish_reason: "stop",
          },
        ],
        usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
      }),
    );
  });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`mock-llm listening on http://127.0.0.1:${PORT}/v1`);
});
