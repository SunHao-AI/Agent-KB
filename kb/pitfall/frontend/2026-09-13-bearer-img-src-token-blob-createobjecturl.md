---
id: kb-20261013-df88
title: 强制 Bearer 鉴权的图片接口：裸 `<img src>` 不带 token 必然 401，必须 blob + createObjectURL
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
confidence: probable
created: '2026-09-13'
updated: '2026-10-13'
severity: medium
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/请求错误提示与BizError.md
---

# 强制 Bearer 鉴权的图片接口：裸 `<img src>` 不带 token 必然 401，必须 blob + createObjectURL

## 背景 / 现象

任务详情时间线的抓拍图全部裂图，后端日志成排 `GET /v1/tasks/images/.../xxx.jpg status=401`（注意 URL 里 `images/images/` 双层是预期：路由段 `/v1/tasks/images/` + DB `image` 列自带的 `images/` 相对前缀，与 `get_task_image_file` 的 `root / image_path` 拼接正好抵消，**不是 bug**）。

## 根因

图片接口挂了 `_: UserInfo = Depends(get_current_user)`，而 `get_current_user` 用 `security = HTTPBearer()` 强要求 `Authorization: Bearer` 头。前端原本把 URL 直接塞进裸 `<img :src="/v1/tasks/images/...">`，由浏览器原生发起资源请求，**不经过 axios**，[request.js] 的 token 注入拦截器对它完全无效 → 必然 401。这是「受保护的二进制资源用 `<img>` 直链」的结构性矛盾，非本项目独有。

## 解决方案

受 Bearer 保护的图片一律走 axios 取 blob，再 `createObjectURL` 喂给 `<img>`，让 token 由拦截器正常注入：

```js

// api/task.js

export const getTaskImageBlob = (imagePath, config = {}) =>

  request({ url: `/tasks/images/${imagePath}`, method: 'get', responseType: 'blob', ...config })

```

组件侧用自定义指令 `v-lazy-image="img.image"` + 一个 `image → objectURL` 缓存：

```js

const imageUrlCache = new Map()      // 图片相对路径 -> objectURL（同图只取一次）

const imageUrlPending = new Map()    // 并发去重

const fetchImageUrl = (image) => {

  if (imageUrlCache.has(image)) return Promise.resolve(imageUrlCache.get(image))

  if (imageUrlPending.has(image)) return imageUrlPending.get(image)

  const p = getTaskImageBlob(image, { silent: true, repeatSubmit: false })

    .then(blob => { const u = URL.createObjectURL(blob); imageUrlCache.set(image, u); return u })

    .finally(() => imageUrlPending.delete(image))

  imageUrlPending.set(image, p)

  return p

}

// 指令：mounted/updated 时异步写 el.src；用 el.__imageKey 防换绑竞态

```

配套三件事：

1. **`request.js` 支持 `silent`**：`if (error.config?.silent) return Promise.reject(error)`，放在通用错误弹框之前。一屏十几张图同时失败时不弹全局 `ElMessage`，只让单图 `console.warn` 降级占位。`responseType:'blob'` 走的是 `error.config.responseType==='blob'` 分支，silent 必须加在该分支之前。

2. **`repeatSubmit: false`**：图片是 GET，理论上不触发防重复提交，但显式关掉更稳。

3. **`onUnmounted` 释放 objectURL**：`imageUrlCache.forEach(URL.revokeObjectURL)` + `clear()`，否则 blob 常驻内存。

## 验证

凡后端接口挂 `HTTPBearer` / `get_current_user`，其返回的图片/文件二进制若要在页面里内联显示，禁止 `<img src>` / `<a href>` 直链该接口，一律 axios blob + `createObjectURL`（下载同理，走 `download()` 或 blob）。若确认资源可公开（如无人脸/车牌敏感），另一条路是后端去掉该接口鉴权，但本项目抓拍图含车辆信息，选择保留鉴权 + 前端 blob。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/请求错误提示与BizError.md` 「强制 Bearer 鉴权的图片接口：裸 `<img src>` 不带 token 必然 401，必须 blob + createObjectURL」
