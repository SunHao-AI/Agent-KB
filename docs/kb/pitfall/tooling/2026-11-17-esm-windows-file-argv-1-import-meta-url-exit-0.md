---
id: kb-20261117-cb78
title: 'ESM 主入口守卫在 Windows 恒为假: file:// 拼 argv[1] 与 import.meta.url 永不相等, 进程 exit
  0 无日志'
type: pitfall
domain:
- tooling
tags:
- esm
- import.meta.url
- pathToFileURL
- tsx
- windows
- silent-exit
- entry-guard
- 主入口守卫
- 秒退
- 静默退出
- 平台差异
- 入口判断
- 跨平台
- auto-reviewed
- promote-to:stack
- needs-scope-review
- promoted
scope: project
status: accepted
confidence: verified
created: '2026-11-17'
updated: '2026-11-17'
severity: medium
summary: 'Node ESM 主入口守卫写成 import.meta.url === `file://${process.argv[1]}` 时, Windows
  下 argv[1] 是反斜杠盘符路径, 拼接结果与规范化的 file:/// 永不一致, tsx 起服务模块加载完即 exit 0 零日志零监听。处置: 用 pathToFileURL(process.argv[1]).href
  比较; 联调期可加 .mts shim 入口绕过(顺带避开 CJS 目录 top-level await 报错)。'
review_by: '2027-11-17'
verified_by: agent
verification:
  evidence: '2026-11-17 联调实测: tsx src/server.ts 秒退 exit 0 端口不监听(两次复现); 同代码 ks-e2e-shim.mts
    入口启动即 listening, /v3 全端点工作'
  reviewed_at: '2026-11-17'
---

# ESM 主入口守卫在 Windows 恒为假: file:// 拼 argv[1] 与 import.meta.url 永不相等, 进程 exit 0 无日志

## 背景 / 现象

MemoryKnowledge 仓 `tsx src/server.ts` 启动服务, 进程立即退出且 exit code 0, 日志只
有一行初始化输出, 无任何报错; 端口不监听。同代码同依赖在 Linux/CI 正常。

## 根因

入口自执行判断写的是:

```ts
if (import.meta.url === `file://${process.argv[1]}) { void startServer(); }
```

Windows 下 `process.argv[1]` 是反斜杠盘符路径(`D:\path\to\server.ts`), 拼出来是
`file://D:\path\...`; 而 `import.meta.url` 永远规范为 `file:///D:/path/...`(三斜杠
+ 正斜杠)。两边永不相等 → 主入口块被跳过 → 模块只完成 import 副作用就退出,
表现是"正常退出码 + 零报错"的静默失败。

## 解决方案

不改业务仓源码的前提下, 写一个不依赖该判断的 shim 入口(放在被测仓 package 内以便
裸导入解析, 用 `.mts` 扩展名强制 ESM——否则 tsx 在 CJS 目录里报 "Top-level await
is currently not supported"):

```ts
// ks-e2e-shim.mts
import { createApp } from "./src/server.js";
import { serve } from "@hono/node-server";
const { app, config } = createApp();
serve({ fetch: app.fetch, port: config.port }, () => {});
```

治本改法(供上游): 用 `import { realpathSync } from "node:fs"` +
`pathToFileURL(process.argv[1]).href === import.meta.url` 比较, 或改用
`process.argv[1]` 与 `fileURLToPath(import.meta.url)` 的路径比较。

## 验证

- 直接 `tsx src/server.ts`: 秒退, 8424 不监听(两次复现);
- `tsx ks-e2e-shim.mts`: 日志 `knowledge service listening on http://localhost:8424`,
  netstat 可见 LISTENING, 全部 `/v3` 端点工作。

## 适用边界与反例

- 该写法在 POSIX 下通常恰好成立(`/` 开头 argv 拼出 `file:///...` 前缀一致), 所以是
  "只在 Windows 发作"的隐性平台缺陷, 单测(CI 常跑 Linux)拦不住。
- 同类失败还有 `require.main === module` 在 ESM 不存在; 跨平台入口判断统一走
  `pathToFileURL(process.argv[1]).href`。
- tsx/vite-node 等 loader 会改写 argv 形态, 判断在"直接 node 跑 dist"与"loader 跑
  src"两种启动方式下结果也可能不同, 入口守卫不要依赖字符串拼接比较。

## 参考

- 该缺陷 2026-10-20 联调时已发现并记录未修(`docs/plans/2026-10-20-observability-b1-b4-followups.md`
  A-1 收口记录), 本次(2026-11-17)以 shim 绕过完成全链路联调。
