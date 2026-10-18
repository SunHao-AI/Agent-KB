---
id: kb-20261012-368d
title: docker exec 探源码"已热载"是误判——无 --reload 容器改码必须 restart
type: pitfall
domain:
- backend
tags:
- docker
- hot-reload
- debugging
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-10-12'
updated: '2026-10-18'
review_by: '2027-04-16'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/授权与台账.md
---

# docker exec 探源码"已热载"是误判——无 --reload 容器改码必须 restart

## 背景 / 现象

（自本条根因段提取）T3 改完后端代码 5 小时后跑联调，签发请求全链静默走旧代码（审计 detail 缺 `expires_in_days`），但 `docker exec` 探针却报 `FORWARD_OK`，一度把排查引向"前端没传字段"的歧途（实际 UI 两次提交都带了）。

## 根因

**根因**：判断容器内后端是否加载了新代码时，用 `docker exec <ctn> python -c "import inspect; ..."` 检查 `inspect.getsource(...)`——这启动的是**新 Python 进程读磁盘文件**，与 uvicorn **运行中进程内存里**的模块版本完全是两回事。setting-backend 容器 uvicorn 无 `--reload`（PID1 cmdline 可证），T3 改完 5 小时后跑联调，签发请求全链静默走旧代码（审计 detail 缺 `expires_in_days`），而 exec 探针却报 `FORWARD_OK`，一度把排查引向"前端没传字段"的歧途（实际 UI 两次提交都带了，`el-input-number` 被 CDP `fill()` 不触发 v-model 是另一个独立坑）。

## 解决方案

**解决方案**：验证"运行态代码"不能看磁盘，要看**行为证据**（如新功能落库留痕、响应新字段）或直接查 `PID1 启动时间 vs 文件 mtime`（`/proc/1/stat` 第 22 字段 + `/proc/stat` btime 换算）。开发联调改完后端一律 `docker restart <ctn>` 再测；容器重启会清空 `/tmp`，放容器里的调试脚本要重新 `docker cp`。附：CDP 自动化填 Element Plus `el-input-number` 时 `fill()/type()` 可能不触发 v-model（`type=number` 不支持 selection 操作），点"增加数值"按钮是模型必更新的可靠姿势。

## 验证

原文实证：setting-backend 容器 uvicorn 无 `--reload`（PID1 cmdline 可证）；T3 改完 5 小时后联调全链静默走旧代码（审计 detail 缺 `expires_in_days`），而 exec 探针却报 `FORWARD_OK`。

## 适用边界与反例

**要点**：`docker exec python` 探针结论只适用于"磁盘代码是否正确"，永远不能证明"进程已加载"；凡是"代码明明改了、行为却是旧的"，第一优先级核对进程启动时间与文件修改时间，而不是怀疑调用方。

## 参考

- 源记录: `docs/known-pitfalls/backend/授权与台账.md`
