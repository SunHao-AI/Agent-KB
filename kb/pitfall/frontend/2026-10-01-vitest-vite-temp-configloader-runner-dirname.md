---
id: kb-20261013-2a55
title: vitest 全量被沙箱拦（.vite-temp）+ `--configLoader runner` 炸 `__dirname is not defined`
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-10-01'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: low
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/测试环境与vitest.md
---

# vitest 全量被沙箱拦（.vite-temp）+ `--configLoader runner` 炸 `__dirname is not defined`

## 背景 / 现象

第六轮给 `task-query.spec.js` 加守卫用例后，`npx vitest run` 全量持续失败（同命令此前多次成功——环境收紧后复现）：

```

failed to load config from .../frontend/vite.config.js

TRAE Sandbox Error: Not allow operate files: .../node_modules\.vite-temp\vite.config.js.timestamp-*.mjs

```

换 `--configLoader runner` 绕开临时文件，又炸：

```

Startup Error: ReferenceError: __dirname is not defined

```

## 根因

1. **vite 默认 `configLoader: 'bundle'`** 会把配置文件（含其依赖）打包成一次性

   `node_modules\.vite-temp\*.mjs` 再 import——沙箱禁止写该路径即整体失败，且报错

   只说 "failed to load config"，看不出真因。

2. **`--configLoader runner` 直接按 ESM import 配置文件**，不经过打包。而

   `package.json` 是 `"type": "module"`：`vite.config.js` 实为 ESM，其中的

   `__dirname` 之所以一直能用，全靠 bundle loader 打包成 CJS 时注入。runner loader

   的纯 ESM 语境下未定义——这是 RuoYi 模板遗留的隐性依赖，dev/build（bundle

   loader）永远测不出来，只有 runner loader 会暴露。

## 解决方案

`vite.config.js` 头部改 ESM 等价写法（两种 loader 通用，dev/build/test 全兼容）：

```js

import { dirname, resolve } from 'path'

import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))

```

`package.json` script 固化 loader，恢复后无需每次带参数：

```json

"test": "vitest run --configLoader runner"

```

测试文件（`*.spec.js`）里的 `__dirname`（如 `pwa-dist.spec.js`）**无需改**——它们经

vitest 的 transform 管线注入 CJS shim，与 config loader 是两条链路。

## 验证

- `npx vitest run --configLoader runner`：**17 files / 195 tests 全绿**（exit 0）；

- 通用判据：`"type": "module"` 项目里 vite/vitest **配置文件**禁用裸 `__dirname`/

  `__filename`/`require`——它们在默认 bundle loader 下是"假可用"，任何绕过打包的

  场景（runner loader、被其它 ESM 工具直接 import）都会炸；测试文件则不受此限；

- 沙箱受限环境下工具报 "failed to load config / failed to ..." 这类**包装错误**时，

  先看附带的 Sandbox Error 行——真因常在第二行，且常有 loader/缓存层级可绕。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/测试环境与vitest.md` 「vitest 全量被沙箱拦（.vite-temp）+ `--configLoader runner` 炸 `__dirname is not defined`」
