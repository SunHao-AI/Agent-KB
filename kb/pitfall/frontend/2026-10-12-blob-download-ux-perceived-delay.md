---
id: kb-20261012-5772
title: blob 下载 UX 体感延迟：后端 200 OK ≠ 浏览器侧下载条出现
type: pitfall
domain:
- frontend
tags:
- blob
- download
- ux
- xhr
scope: stack
status: accepted
severity: medium
confidence: probable
created: '2026-09-12'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/上传与文件处理.md
---

# blob 下载 UX 体感延迟：后端 200 OK ≠ 浏览器侧下载条出现

## 背景 / 现象

「导出管理」列表点「打包下载」`button`（`data-test="pack-download"`），容器 `flysee-video-setting` 立刻打日志 `INFO: GET /v1/exports/{id}/download HTTP/1.1 200 OK`，但浏览器侧（包括 Chrome/Edge 下载面板）的下载条**要等好几秒后才出现**，期间按钮也无反馈。用户很容易把这体感延迟误判为「按钮点了没反应」或「请求挂了」。

（先排三色再定位）：
1. 排除 CORS：Vite dev proxy 让浏览器只走同源 127.0.0.1:5173，**没有 OPTIONS 二次往返**，不会卡跨域握手
2. 排除「按钮被 disabled 状态吃」：模板已经 `:disabled="!downloadable(row.status)"`，状态非 downloadable 时按钮就已 disabled；该用户能点到说明状态正常
3. 真因：axios `responseType: 'blob'` 的**浏览器侧 Blob 累积语义**

## 根因

（按时间序列）：
| 时刻 | 事件 |
| --- | --- |
| t₀ | 用户点击「打包下载」，`handleDownload` 调 [downloadExport(id)](file:///d:/WorkPlace/Pycharm/flysee-video-setting/frontend/src/api/exports.js) |
| t₁ | 后端 `FileResponse` 首字节返回（TTFB），uvicorn 写 `200 OK` 日志。**此时用户看到的"200 OK"** |
| t₁→t₂ | 后端继续 body 流式输出 50MB，经历 Docker Desktop `vmware-natd` / Hypervisor / Vite dev proxy（5173→8099）→浏览器 XHR 累积到 `event.target.result` 为完整 `Blob` 的 tag。无 `progress` 事件可用 |
| t₂ | XHR `readyState=4` + `status=200` + `responseType=blob` → axios resolve `blob` |
| t₃ | handler `.then(blob)` 跑：`URL.createObjectURL(blob)` → 拼 `<a>` → `a.click()` → 浏览器下载面板出现 |

## 解决方案

[views/exports/index.vue:723](file:///d:/WorkPlace/Pycharm/flysee-video-setting/frontend/src/views/exports/index.vue#L723) `handleDownload`：
- 函数顶部追加 9 行注释（含 3 步时间序列），同模板 [`create_export` 端点](file:///d:/WorkPlace/Pycharm/flysee-video-setting/backend/api/v1/exports.py#L40-L56)「后端日志 = TTFB，不是 E2E 完成」的注释风格一致
- `downloadExport(row.id)` 调用前先 `ElMessage({ message: '正在下载，本包较大（约 X），浏览器缓冲字节后开始保存', type: 'info', duration: 5s })`；`X` 直接读 `row.file_size`，复用 `formatFileSize` 展示后端已格式化字段（项目约定：前端不二次格式化）。**注意：此处曾用 `ElMessage.info(msg, {duration})` 的错误写法并引发整条下载链路静默失效，见下一条目「ElMessage 简写第二参是 appContext」**
- `<a>` 标签加 `a.rel='noopener'`（防御 blob: URL 上 pointer 事件继承——对 blob 协议不一定起作用但免费的好处不丢）

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

通常是数秒到十几秒：**axios 没有任何 readable 事件能告诉 UI「已读了 X MB」——XHR blob 模式在浏览器端是「攒完才 resolve」的终结事件**。这段空窗**不是 bug**，是 blob 下载的物理下限；axios 1.x fetch 适配器即使启用了也没改变浏览器端 `body` 等待语义（`responseType: 'blob'` 是回应整段）。

容器日志的 `200 OK` 是 TTFB 指标，**不是端到端完成指标**。用户看后端日志判断"接口通了"，看前端 UI 判断"下载开始了"，两者不在一刻——这就是体感延迟的根。

- ❌ 加按钮 `:loading` —— 治标且与 `:disabled` 状态跳转冲突，按钮点击期间 `body` 流读不完仍看不到下载条
- ⚠️ ~~改原生 `<a href>` —— a[href] 不能自定义 Authorization header（query 传 Bearer token 把 secret 暴露到访问日志，安全性退化，不推荐）~~ **已被后续条目推翻**：正确做法是 query 传「短时签名票据」而非 Bearer 本身，见下方「blob 攒内存 OOM 隐患 → 改短时签名 URL 原生下载」
- ✅ **UI 信息暴露**：`handleDownload` 入口用 `ElMessage.info` 主动告知"已发起、量大、浏览器缓冲字节后开始保存"，把不可避免的空窗转化为已知等待；不动协议、不动后端、token 不出 URL

- 同模板下一组 blob 下载（`getDiff` [.zdiff](file:///d:/WorkPlace/Pycharm/flysee-video-setting/frontend/src/api/exports.js)、未来新增的 `download*` 函数）入口统一加 `ElMessage({ message: '正在下载…', type: 'info' })`，把空窗显式化
- 接收 `formatFileSize(row.file_size)` 作为提示中的大小来源——后端已格式化，前端不再二次拼接
- 项目的 blob 下载链条规范：**「长 timeout（上一轮约定）+ 下载中 toast（本轮约定）」是配套约定**，新 blob 接口必须都写
- 后端给 `FileResponse` 自动 `Content-Disposition: attachment; filename=...` 时保持明确（本端点已在 [FileResponse](file:///d:/WorkPlace/Pycharm/flysee-video-setting/backend/api/v1/exports.py#L169) 上不传 `filename`，由前端 `<a download=zapkFilename(row)>` 补；如未来切到原生 `<a href>` 必须让后端塞 filename，前端不重复拼，避免"前后端两份拼名"的漂移——参考 [应用包闭环形态.md](../frontend/应用包闭环形态.md) 同名问题）

参见同目录上一轮条目「大文件下载走全局 10s 超时被 axios abort」：那轮修的是 **错误**（abort + 超时 toast），本轮修的是 **体验**（成功路径的体感空窗），两者独立不矛盾。

## 参考

- 源记录: `docs/known-pitfalls/frontend/上传与文件处理.md`
