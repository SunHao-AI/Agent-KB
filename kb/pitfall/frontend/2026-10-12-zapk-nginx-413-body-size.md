---
id: kb-20261012-2a96
title: .zapk 安装被 nginx 反代 413 拦截（client_max_body_size 默认 1m）
type: pitfall
domain:
- frontend
tags:
- nginx
- upload
- reverse-proxy
- deploy
scope: stack
status: accepted
severity: high
confidence: probable
created: '2026-09-12'
updated: '2026-10-18'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/frontend/应用包闭环形态.md
---

# .zapk 安装被 nginx 反代 413 拦截（client_max_body_size 默认 1m）

## 背景 / 现象

web 前端「算法方案」页点「开始安装」上传几百 MB 的 `.zapk`，页面提示「系统接口413异常」（`request.js` 对 `Request failed with status code 413` 的统一包装）。后端 FastAPI 日志**完全没有**该请求的痕迹——请求根本没到后端。

## 根因

web 前端是生产构建（`Dockerfile.prod` → nginx 托管 + `/v1/` 反代 `backend:17998`，见 `frontend/nginx.conf`）。nginx `client_max_body_size` **默认 1m**，超大 multipart 在 nginx 请求体校验阶段直接返回 413，不会转发到后端。前端 `installSuite` 的 `timeout: 300000` 只管 axios 超时，管不到反代的体积限制；后端也没有任何 body size 配置（FastAPI/uvicorn 默认不限），所以 413 只可能来自 nginx 这一跳。

## 解决方案

（改 `flysee_video_web/frontend/nginx.conf` 的 `location /v1/`，与页面「>500MB 属正常」口径对齐）：

```nginx
client_max_body_size 2g;        # 默认 1m 必炸；.zapk 几百 MB 起步
proxy_read_timeout 300s;        # 安装是同步长耗时（整包解密落盘），与前端 timeout 对齐
proxy_send_timeout 300s;
proxy_request_buffering off;    # 大文件不在 nginx 整包缓冲，流式转发
```

## 验证

源记录未单列"验证"段（2026-10-18 回溯核对 `docs/known-pitfalls/frontend/应用包闭环形态.md`），验证方法已并入「适用边界与反例」段首：`docker exec flysee-video-web-frontend nginx -T | Select-String client_max_body_size` 确认配置生效（改 `nginx.conf` 须重建镜像才生效）；行为侧判据为后端日志出现该请求（413 拦截时后端零痕迹）。

## 适用边界与反例

`nginx.conf` 是 **COPY 进前端镜像**的（非 bind mount），改完必须 `dev.ps1 -Build`（或单独 `docker compose build frontend; up -d frontend`）重建才生效；验证用 `docker exec flysee-video-web-frontend nginx -T | Select-String client_max_body_size`。

- 上传接口报 413 且**后端日志无该请求** → 先查中间层（nginx / 网关 / 云 LB）的 body size 限制，不要在后端找"上传大小校验"代码。
- 前端为容器化 nginx 生产构建时，**任何反代参数（体积、超时、buffering）都是部署面配置**，改 `frontend/nginx.conf` 等同于改前端代码，要走 `-Build`；纯 API 超时（axios timeout）与反代超时（proxy_read_timeout）是两层，慢接口必须两头同时对齐，否则前端 300s、nginx 60s 会把长任务掐成 504。

## 参考

- 源记录: `docs/known-pitfalls/frontend/应用包闭环形态.md`
