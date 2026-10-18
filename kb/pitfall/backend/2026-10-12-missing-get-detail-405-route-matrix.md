---
id: kb-20261012-b4e0
title: 角色详情 GET 接口缺失导致前端 405（FastAPI 路径路由按方法匹配）
type: pitfall
domain:
- backend
tags:
- fastapi
- routing
- http-405
- crud
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-01'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/权限与接口路由.md
---

# 角色详情 GET 接口缺失导致前端 405（FastAPI 路径路由按方法匹配）

## 背景 / 现象

> 面向：`flysee-video-setting` 后端（FastAPI）。

**现象**：容器 `flysee-video-setting` 日志出现 `GET /v1/system/roles/R001 HTTP/1.1" 405 Method Not Allowed`，而 `GET /v1/system/roles` 列表、`POST /v1/system/roles` 创建、`PUT /v1/system/roles/{code}` 更新、`DELETE /v1/system/roles/{code}` 删除均 200。前端「角色管理」页编辑某角色时菜单树勾选状态回显失败（fetch 详情 405，旧 `try/catch` 静默吞掉）。

## 根因

**根因**：
1. **后端路由矩阵遗漏** —— [role.py](../../../backend/api/v1/auth/role.py) 在 `/v1/system/roles/{code}` 路径只注册了 `PUT` 与 `DELETE`，没有 `GET` 详情端点。FastAPI 的 Starlette routing 按 **路径 × HTTP 方法** 联合匹配：路径命中但方法不命中 → 统一返回 **405 Method Not Allowed**（而不是 404）。这是 FastAPI/Starlette 的标准行为——开发人员常错把这种 405 当成前端方法用错，实际是后端漏定义方法。
2. **前端依赖详情数据唯一回显路径** —— [role/index.vue](../../../frontend/src/views/system/role/index.vue) 的 `openEdit(row)` 用 row 数据仅填基础字段，但 `menu_codes`（菜单授权列表）必须调 `getRole(code)` 单独查，否则 `el-tree` 无法回显。前端 [api/system/role.js](../../../frontend/src/api/system/role.js) 的 `getRole` 走 `GET /system/roles/{code}`，正好命中上面"段匹配方法不支持"。
3. **跨副本代码漂移** —— 生产镜像（`flysee-video-setting-app`）的代码保存在镜像可写层，本地 `docs`/源码落后于生产镜像；开发者在本机工作区看不到 fix → 默认认为后端「从未实现」过 GET 详情端点。

## 解决方案

**解决**：
- **后端三段补代码（service 透传 + provider 查询 + API 路由）**：
  - `MySQLAuthProvider.get_role(role_code)`：按 `role_code` 精确查询（`SysRole.is_del == 0`），不存在抛 `AUTH_400`，命中走已有 `_role_out` 完整序列化（含 `menu_codes`）；
  - `RoleService.get(code)` 透传到 `provider.get_role`；
  - `@router.get("/{code}")` 路由加 `require_perm("sys:role:list")`（与列表一致，详情页不需新增权限）。
- **重启容器兑现代码**：`docker restart flysee-video-setting-backend`，确认 `docker ps` healthy 后用 curl 验证 `GET /v1/system/roles/R001` 不再 405（未登录 → 401 `AUTH_020` 证明路由已注册）。

## 验证

原文「解决」段：`docker restart flysee-video-setting-backend` 确认 healthy 后 curl 验证 `GET /v1/system/roles/R001` 不再 405（未登录 → 401 `AUTH_020` 证明路由已注册）。

## 适用边界与反例

**排错要点**：
- 看到 405 先检查 **当前进程的 API 路由元信息**，别只看磁盘文件。判定命令：
  `docker exec <c> python -c "import backend.main as m; [print(r.path, list(r.methods)) for r in m.app.routes if hasattr(r, 'methods')]"`
  路径命中但方法缺失 → 后端漏路由；路径未命中 → 前端路径拼错。
- 如果磁盘上有 fix 但容器仍 405，多半是 uvicorn 进程未 reload（见「容器进程未重启导致运行旧 Schema」），restart 即可。

**规范**：
- 凡提供「列表 + 单条 CRUD」的资源，**GET 列表 / GET 单条 / POST 创建 / PUT 更新 / DELETE 删除** 五方法必须在同一路由组同时定义；缺任一切面都会让前端某块数据回显静默失败，且表现常是 405 / 404 而非业务异常。
- 路由矩阵变更后（如新增 GET 详情），前端所有对该资源的请求都应能从后端 `/openapi.json` 中查到，作为快速对账工具。
- 跨容器调试坑：prod 模式代码 baked 进镜像可写层，宿主机 `docker exec cat` 看到的才是「真盘」，不能在宿主机源码目录断言「没实现」。

## 参考

- 源记录: `docs/known-pitfalls/backend/权限与接口路由.md`
