---
id: kb-20261012-0995
title: 重 CPU/IO 端点写成 `async def` 冻结事件循环：前端 10s 超时先 abort（`net::ERR_ABORTED`）
type: pitfall
domain:
- backend
tags:
- event-loop
- threadpool
- axios-timeout
- err-aborted
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-10'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/性能与容错优化.md
---

# 重 CPU/IO 端点写成 `async def` 冻结事件循环：前端 10s 超时先 abort（`net::ERR_ABORTED`）

## 背景 / 现象

**现象**：导出/发布页点"创建导出"，浏览器控制台报 `net::ERR_ABORTED http://127.0.0.1:5173/v1/exports`，UI 提示失败；但刷新后列表里其实已经有新记录，后端 uvicorn 访问日志也是 `POST /v1/exports 200 OK`。同时段其他接口（如 `GET /v1/clients`）也一起被 abort。

## 根因

**根因**（两层叠加，缺一不可）：

1. `backend/api/v1/exports.py::create_export_api` 声明为 `async def`，内部调用的 `create_export` 在 `export_worker_mode="inline"`（默认）下是**纯同步重活**：读取全部模型权重 → 逐个 SHA256 → `pack_zapk` 打包 → 写盘。`sys_oper_log.cost_ms` 实测 50MB 包 **53~59s**。`async def` 里跑同步代码 = 直接霸占事件循环，这 55s 内**全站所有请求排队**（这解释了"连 `GET /v1/clients` 也被 abort"）。
2. `frontend/src/utils/request.js` 全局 `timeout: 10000`。10s 到点 axios abort → 浏览器侧 `ERR_ABORTED`；后端不感知客户端断开，继续跑完并落库返回 200。于是形成"前端报错、后端成功"的错觉。

## 解决方案

**方案**（两处都要改，只改一处会残留另一半年症状）：

```python
# backend/api/v1/exports.py —— 同步 def，FastAPI 自动放 threadpool，不占事件循环
@router.post("", response_model=ApiResponse)
def create_export_api(data: CreateExportRequest, db: Session = Depends(get_db), ...):
    ...
```

```js
// frontend/src/api/exports.js —— 单接口放宽超时，不动全局 10s
export function createExport(data) {
  return request({ url: '/exports', method: 'post', data, timeout: 300000 }).then(r => r.data)
}
```

## 验证

原文「验证方法」段(实测): 改后 `POST /v1/exports` 仍耗时 23889ms, 但同窗口 40+ 次 /health 探测全部 200 且 ≤0.83s, 控制台无 ERR_ABORTED; 改前 `sys_oper_log.cost_ms` 实测 50MB 包 53~59s。

- **验证方法**（改完后端到端确认线程池真的生效）：一边从 UI 提交导出，一边用宿主机循环 `curl -w "%{http_code}" %{time_total}` 探测 `/health`。改前打包期探测会阻塞十几秒；改后 `POST /v1/exports` 仍耗时 23889ms，但同窗口 40+ 次 `/health` 探测全部 200 且 **≤0.83s**，控制台无 `ERR_ABORTED`。单看"接口返回 200"不足以证明修复——改前也是 200，差别在**其它接口是否被连带卡住**。

## 适用边界与反例

**要点**：

- **`ERR_ABORTED` 是客户端主动中止，不是服务端错误**。排查顺序应先查 `sys_oper_log.cost_ms`（或 uvicorn 访问日志的时间戳）确认服务端真实耗时，再判断是否超时，别一上来改前端。
- **含同步重活的端点一律用 `def` 而非 `async def`**。Starlette 对 `def` 端点走 `run_in_threadpool`，对 `async def` 端点直接在事件循环里执行——后者只要有一段同步 CPU/IO 就会拖垮整站并发。
- 单接口超时覆写优先于改全局 `timeout`：全局值是为普通 CRUD 设计的，调大会掩盖其他接口真实的性能退化。
- 定位手段：`docker exec flysee-video-setting-mysql mysql ... "SELECT request_url, response_code, cost_ms FROM fs_uav_auth.sys_oper_log ORDER BY id DESC LIMIT 10"`，一眼看出哪个接口在拖。
- 更彻底的方案是 `export_worker_mode="thread"` 后台打包 + 前端轮询 `progress`，但需要列表/弹窗配合展示 `packing` 态，属功能改动而非缺陷修复。

## 参考

- 源记录: `docs/known-pitfalls/backend/性能与容错优化.md`
