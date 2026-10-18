---
id: kb-20261013-5cc1
title: '`/system/logs/download` 漏挂 `get_current_user` → 匿名可拉全量服务日志（敏感信息泄漏）'
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-21'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: high
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/认证与锁屏.md
---

# `/system/logs/download` 漏挂 `get_current_user` → 匿名可拉全量服务日志（敏感信息泄漏）

## 背景 / 现象

> 面向：`flysee_video_web` 后端 `api/v1/system.py`。

## 根因

该端点声明只写了 `Query` 参数，**漏了 `_: UserInfo = Depends(get_current_user)` 依赖**；而 `LicenseMiddleware` 的白名单只管"授权过期时是否放行"，不承担登录鉴权——FastAPI 端点没有 auth 依赖就是完全匿名可访问。中间件与端点依赖是两层独立防线，**中间件放行 ≠ 端点需要登录**。

排查中两个差点误判的细节：

- 不带 `levels` 参数时响应 200 **bytes=0**：`_match_level` 对空 level_set 恒 False，看起来像"被拦截了"。实际是过滤逻辑把全部行滤空——**200 空 body ≠ 鉴权生效**，必须带齐参数拿非空 body 才算决定性证据。

- dev 环境 backend 是 uvicorn `--reload`，加依赖后 8 秒内自动生效，但 SSE 在途连接会把 reload 拖慢（graceful shutdown 等待），验证前先 `docker logs` 确认 `Reloading...` + `Application startup complete` 再复测，否则会把"还没 reload"误判成"改了没用"。

## 解决方案

补依赖并写防回归用例（`tests/test_security.py`）：

```python

@router.get("/logs/download")

def download_logs(

    lines: int | None = Query(None, ge=1, le=100000),

    ...,

    _: UserInfo = Depends(get_current_user),

) -> Response:

# tests/test_security.py

def test_logs_download_requires_auth(client):

    resp = client.get("/v1/system/logs/download", params={"lines": 10, "levels": "INFO"})

    assert resp.status_code == 401

```

## 验证

补依赖并写防回归用例（`tests/test_security.py`）。决定性证据口径：不带 `levels` 参数时响应 200 **bytes=0**——`_match_level` 对空 level_set 恒 False，看起来像"被拦截了"，实际是过滤逻辑把全部行滤空；**200 空 body ≠ 鉴权生效**，必须带齐参数拿非空 body 才算决定性证据。dev 环境加依赖后 8 秒内自动 reload，但 SSE 在途连接会把 reload 拖慢，验证前先 `docker logs` 确认 `Reloading...` + `Application startup complete` 再复测。

## 适用边界

- **新增任何返回业务数据/文件内容的端点，函数签名必须带 `Depends(get_current_user)`**；code review 时把"函数签名里没有 auth 依赖"当硬性检查项（对照同 router 其他端点抄依赖最容易漏的是"后来补的端点"）。

- 鉴权验证必须用**能产生非空结果的最小参数集**做匿名请求，断言 401；只看状态码或空 body 会被过滤逻辑骗过。

- 端点级自查一行命令：`grep -rn '@router\.' backend/api/v1 | 与 grep 'get_current_user' 对照`，无 auth 依赖的端点逐个确认是否有意匿名（登录/健康检查/license-state 脱敏视图）。

## 参考

- 源记录: `docs/known-pitfalls/backend/认证与锁屏.md` 「`/system/logs/download` 漏挂 `get_current_user` → 匿名可拉全量服务日志（敏感信息泄漏）」
