---
id: kb-20261012-fa94
title: '`.zdiff` 增量包下载 OOM 隐患：`get_diff` 落盘 + `FileResponse` 流式（顺带踩到 `FileResponse`
  没有 `content_length` 形参）'
type: pitfall
domain:
- backend
tags:
- starlette
- file-response
- streaming
- oom
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-12'
updated: '2026-10-13'
review_by: '2027-04-11'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/性能与容错优化.md
---

# `.zdiff` 增量包下载 OOM 隐患：`get_diff` 落盘 + `FileResponse` 流式（顺带踩到 `FileResponse` 没有 `content_length` 形参）

## 背景 / 现象

**现象/背景**：`.zapk` 走「短时签名票据 + 原生 `<a href>` 流式下载」改造后（见前端「axios responseType:blob 下载大文件」条目），`.zdiff` 增量包仍是旧链路：`get_diff` 用 `result.pack()` 在内存里构建整个 zip 再经 `StreamingResponse(bytes)` 返回。diff 包与 `.zapk` 同量级（≈ model 体积），100GB 包 = 进程峰值 ≈ 200GB（pack buffer + BytesIO 句柄两份）→ OOM。

## 根因

旧链路是"先在内存 pack 出完整 bytes 再交给 StreamingResponse(bytes)"——对整包字节而言流式发送并不省内存, 峰值内存由包体积决定(≈100GB 包同时驻留 pack buffer 与 BytesIO 句柄两份); 只有先落盘再让 FileResponse 按路径分块 stat 发送, 内存才与包大小解耦.

## 解决方案

**解决（落盘 + 流式）**：[export_service.get_diff](file:///d:/WorkPlace/Pycharm/flysee-video-setting/backend/services/export_service.py) 改为把 diff 包写盘到 `EXPORT_DIR/diff_<client_id>_<fv>_<tv>.zdiff` 并返回 `(path, from_ver, to_ver, size)`；端点 [GET /{export_id}/diff](file:///d:/WorkPlace/Pycharm/flysee-video-setting/backend/api/v1/exports.py) 用 `FileResponse(path)` 64KB 分块流式发送，磁盘 I/O 不重复、内存恒定。文件名稳定（含 client_id + 两版本）→ 同对重算直接覆盖、幂等返回 size。

## 验证

原文实录(pytest 抓到): 传 `content_length` 触发运行期 `TypeError: FileResponse.__init__() got an unexpected keyword argument 'content_length'`, `test_diff_download` 直接红; `py_compile`/import 都抓不到该类运行期错误。

## 适用边界与反例

**踩到的真实 bug（pytest 抓到）**：写端点时给 `FileResponse(path, content_length=diff_size, ...)` —— **starlette `FileResponse.__init__()` 根本没有 `content_length` 形参**，运行期 `TypeError: FileResponse.__init__() got an unexpected keyword argument 'content_length'`，`test_diff_download` 直接红。`FileResponse` 在 `__init__` 内对路径 `os.stat` 自动取 `Content-Length`（并在 stat 失败时才退 `stat().st_size`），**无需也不能显式传**。修正：解包用 `_diff_size` 占位（本端点不需要它），`FileResponse` 只传 `path / media_type / headers`。

**要点**：
- **starlette 响应类形参不要凭直觉臆造**：`FileResponse(path, status_code, headers, media_type, filename, stat_result, content_disposition_type)`——没有 `content_length`；要设长度用 `stat_result=os.stat(...)` 或直接让默认 stat 生效。改完**必须跑到对应端点的 e2e**（`test_api_exports.py::test_diff_download`），`py_compile` / import 都抓不到这种运行期 `TypeError`。
- **diff 落盘的文件名稳定即幂等**：`diff_<c>_<fv>_<tv>.zdiff` 含全部决定内容的关键字段，同对重算先 `os.path.exists` 命中就直接 `os.path.getsize` 返回，不重复 `pack()`（省一次整包内存峰值 + 重算）。删除导出时应一并清对应 diff 文件，避免磁盘堆积。
- **diff 端点同样要 fail-closed**：与 `.zapk` 共用 `require_perm_or_signed` + `?ticket=`，端点内 `ctx is None 且 owner_id is None` 两分支都不满足时 `raise 401`，杜绝匿名全量拉任意客户端的模型增量。
- **进度反馈复用同一套前端探测**：diff 下载也走 `probeDownloadMeta(url)` 的 HEAD（`content-length`/`content-range`）+ `DownloadProgressGuide` 引导弹窗，`.zdiff` 用 `diffResult.total_size` 兜底 total。

## 参考

- 源记录: `docs/known-pitfalls/backend/性能与容错优化.md`
