---
id: kb-20261013-6b02
title: '`CORSMiddleware` 注册在授权中间件内侧：preflight 被授权链拦成 403、授权失效被浏览器误报成 CORS 错误'
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-03'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: medium
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/授权三态与离线容器.md
---

# `CORSMiddleware` 注册在授权中间件内侧：preflight 被授权链拦成 403、授权失效被浏览器误报成 CORS 错误

## 背景 / 现象

`CORS_ORIGINS=["*"] + allow_credentials=True` 是显式的带凭证跨域接入意图，但旧顺序（先 `add_middleware(CORSMiddleware)` → 位于**最内层**）导致：

- `OPTIONS /v1/tasks`（浏览器 preflight）→ **403**，`ACAO=None`：握手探测竟然要先过授权判定，`CORSMiddleware` 的 preflight 短路根本没机会执行；

- 授权链短路的 `403`（未初始化/过期/宽限禁写）→ **无 `Access-Control-Allow-Origin`**。

后果不是"样式问题"而是**语义篡改**：跨域场景浏览器把 403 判成 CORS 失败并在 console 报 `No 'Access-Control-Allow-Origin'`，前端 `fetch` 直接 reject，**读不到响应体里的 `E_LICENSE_001/003/004`**，授权到期引导页、未初始化跳转、宽限期禁写提示全部失效——用户只看到"网络错误"。

## 根因

Starlette 的中间件**后注册者在外层**。`CORSMiddleware` 只能给"流经自己"的响应补 CORS 头、也只在流经自己时才应答 preflight。把业务/授权中间件注册在它**之后**（=外层），它们就有权在 CORS 之前把请求拦掉，于是：授权 403 绕过了 CORS、preflight 撞上授权墙。

## 解决方案

把 `CORSMiddleware` 移到 `LicenseMiddleware` **之后**注册（→ 位于其外层），最终执行序：`ServerError → NoStoreAPI → CORS → License → RequestContext → ExceptionMiddleware → 路由`。

```python

app.add_middleware(RequestContextMiddleware)

app.add_middleware(LicenseMiddleware)

app.add_middleware(CORSMiddleware, ...)   # 必须后注册 = 外层

app.add_middleware(NoStoreAPIMiddleware)

```

复验：preflight `OPTIONS` → **200 + ACAO**（不进授权链）；授权 `403` → **带 ACAO**，浏览器能正常读到 `E_LICENSE_*`；授权拦截语义不变（非白名单仍 403）。新增 2 例回归锁死：`test_cors_outermost_license_blocked_still_has_cors_headers`（顺序回归）、`test_middleware_layer_db_error_maps_503_json`（联动 D11）。全量 **546 passed**。

## 验证

`BaseHTTPMiddleware`（授权中间件）内部抛的异常**能**被 `@app.exception_handler(Exception)` 收敛：探针把 `_load_config` 打成 `OperationalError`，实测返回 `503 application/json {"code":10006,...}`。原因是 `Exception` handler 挂在 `ServerErrorMiddleware`（**最外层**），位于所有用户中间件之外；而 `@app.exception_handler(具体异常类)` 挂在 `ExceptionMiddleware`（**用户中间件内层**），够不着中间件层抛的异常。**要给中间件层做统一异常呈现，只能装在 `Exception` handler 里再 `isinstance` 分流**（D11 的实现方式由此得到证实）。

## 适用边界

- **`CORSMiddleware` 必须是最后一个业务中间件之外的最后一层**（即注册在授权/鉴权/限流等**之后**）。跨域接入下，任何"在 CORS 之前短路"的中间件都会把自己的业务语义（403/429）**伪装成 CORS 错误**，前端从此读不到任何业务错误码——这类 bug 在同域开发环境 100% 不可见，只在跨域接入时爆发。

## 参考

- 源记录: `docs/known-pitfalls/backend/授权三态与离线容器.md` 「`CORSMiddleware` 注册在授权中间件内侧：preflight 被授权链拦成 403、授权失效被浏览器误报成 CORS 错误」
