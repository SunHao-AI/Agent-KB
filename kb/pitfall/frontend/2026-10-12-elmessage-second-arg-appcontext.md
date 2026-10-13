---
id: kb-20261012-75b9
title: '`ElMessage.info(msg, {duration})` 的第二个参数是 `appContext` 而非 options —— 抛 TypeError
  被空 catch 吞成「按钮点了完全没反应」'
type: pitfall
domain:
- frontend
tags:
- element-plus
- error-handling
- debugging
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-12'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/上传与文件处理.md
---

# `ElMessage.info(msg, {duration})` 的第二个参数是 `appContext` 而非 options —— 抛 TypeError 被空 catch 吞成「按钮点了完全没反应」

## 背景 / 现象

「导出管理」页「打包下载」（`data-test="pack-download"`）与部署指引抽屉里的「再次下载 .zapk」（`data-test="redownload"`）**两个按钮点击后前后端全无反应**：无 toast、无 loading、Network 面板无新增请求、后端容器日志无该请求、浏览器 Console 一片安静（`(none)`）。

## 根因

（Element Plus `ElMessage` 的签名陷阱）：

```js
// node_modules/element-plus/es/components/message/src/method.mjs
messageTypes.forEach((type) => {
  message[type] = (options = {}, appContext) => {   // ← 第二参是 Vue appContext！
    const normalized = normalizeOptions(options);
    return message({ ...normalized, type }, appContext);
  };
});
// createMessage 内：vnode.appContext = context || message._context;
```

写成 `ElMessage.info(msg, { duration: 5000 })` 时：
1. 第一参 `msg` 是 string → `normalizeOptions` 正确得到 `{message: msg}`，**duration 根本没生效**
2. 第二参 `{duration:5000}` 被当成 `appContext` 赋给 `vnode.appContext`
3. `render(vnode, container)` → `createComponentInstance` 内部执行 `Object.create(appContext.provides)`，而普通字面量对象**没有 `provides`** → `Object.create(undefined)` → 抛 `TypeError: Object prototype may only be an Object or null: undefined`

于是异常发生在 `await downloadExport(row.id)` **之前**：请求从未发出（后端必然无日志）。而 `handleDownload` 的 `catch (e) { /* 错误已由 request 拦截器统一提示 */ }` 是**空的** —— 该注释只覆盖 axios/HTTP 错误，JS 异常走不到拦截器，异常就此蒸发。**这就是「前端无 toast + 后端无请求 + 控制台无报错」三零现象的完整成因。**

## 解决方案

- [views/exports/index.vue](file:///d:/WorkPlace/Pycharm/flysee-video-setting/frontend/src/views/exports/index.vue) `handleDownload` 的下载中提示改**对象形式**：`ElMessage({ message: '…', type: 'info', duration: 5 * 1000 })`
- 同函数空 `catch` 补兜底：`console.error("[exports] 打包下载失败:", e)` + `ElMessage({message: '打包下载失败：' + (e?.message||'未知错误'), type:'error', duration: 5*1000})`，并用 `if (e?.__toasted) return` 跳过拦截器已提示的错误
- [utils/request.js](file:///d:/WorkPlace/Pycharm/flysee-video-setting/frontend/src/utils/request.js) 在**所有已 toast 的** reject 分支给 error 打 `__toasted = true`（含 blob 分支；blob 的 `.catch` 会二次捕获自己 `then` 里 reject 的 `bizErr`，必须先判 `__toasted` 透传，否则一次失败弹两条 toast）

## 验证

1. `document.addEventListener('click', …, true)` 捕获监听 → 证明**原生 click 确实到达**目标 button（排除「事件没绑」「被遮挡吃点击」）
2. 对照点击同页「部署指引」→ 抽屉正常打开 → 证明 click→handler 链路本身健康
3. 沿 `el.__vueParentComponent.parent` 上溯组件链，找到 `Exports` 组件的 `setupState`，**直接调 `dd.emit('redownload')`** → 仍无反应 → 排除 emit 链路
4. **直接调 `setupState.handleDownload(setupState.guideRow)`** → 仍无反应 → 锁定函数体内部
5. 把函数体逐语句拆开在页面里重放：`formatFileSize(row.file_size)` ✅ 返回 `175.66 MB`；`downloading[row.id]=true` ✅；**`ElMessage.info(msg,{duration})` ❌ 抛 TypeError**
6. 抓 stack：`createMessage → render → createComponentInstance → Object.create(<anonymous>)`；读 `method.mjs` 源码印证签名
7. 三态收口验证：`EM.info('x')` ✅ / `EM({message,type,duration})` ✅ / `EM.info('x',{duration})` ❌

## 适用边界与反例

这不是「事件没绑定」——上一轮的「blob 下载 UX 体感延迟」条目为解决空窗而加的 `ElMessage.info` 恰是本次回归源头。

页面按钮 `@click="handleDownload(row)"`，抽屉按钮 `@redownload="() => handleDownload(guideRow)"`，殊途同归都进同一函数。

- **`ElMessage` 需要任何自定义项（`duration`/`showClose`/`onClose`/`appendTo`/`placement`）时，一律用对象形式 `ElMessage({message, type, duration})`；简写 `ElMessage.success/info/warning/error(msg)` 只允许传一个参数**（`ElMessageBox` 的 `(message, title, options)` 三参形式是另一套 API，别混）
- **`catch` 里严禁只留注释不写任何动作**。项目里「错误已由 request 拦截器统一提示」这个约定**只对 axios 错误成立**，JS 异常（API 误用、`.join is not a function`、`undefined.x` 等）拦截器管不到；catch 至少要 `console.error(tag, e)`，否则故障静默蒸发、只能靠插桩从头挖
- 判据速记：**「点击后三零」（无 UI 反馈 + 无网络请求 + 无 Console 报错）→ 优先怀疑 handler 内 `await` 之前的同步语句抛错且被空 catch 吞**，而不是怀疑事件绑定
- 浏览器插桩三板斧（本仓 `browser_evaluate` 注意：**只认箭头函数，写 `function(){}` 会稳定返回 `undefined`**；脚本用顶层 `return` 而非 IIFE）：① 捕获阶段 click 监听验事件到达 ② 健康对照按钮 ③ `el.__vueParentComponent` 上溯取 `setupState` 直接调函数 / 逐语句重放

## 参考

- 源记录: `docs/known-pitfalls/frontend/上传与文件处理.md`
