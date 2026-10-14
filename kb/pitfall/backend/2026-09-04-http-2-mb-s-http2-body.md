---
id: kb-20261013-6eb5
title: HTTP/2 大文件上传被钳到 1~4 MB/s：`http2_body_preread_size`（默认 64k）就是 h2 接收窗口，别错选 `http2_chunk_size`
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-04'
updated: '2026-10-13'
severity: high
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/构建与开发环境.md
---

# HTTP/2 大文件上传被钳到 1~4 MB/s：`http2_body_preread_size`（默认 64k）就是 h2 接收窗口，别错选 `http2_chunk_size`

## 背景 / 现象

任务创建页上传 645MB 视频，进度条"预计还需 5 分 18 秒"，实测 **4.1 MB/s**。用户怀疑网络代理。逐层压测排除：容器内写盘 62.9 MB/s、直连 uvicorn 47 MB/s、同 443 端口 curl **HTTP/1.1** 85 MB/s，唯浏览器（nginx 日志 `POST /v1/videos HTTP/2.0`）**4.1 MB/s** → 瓶颈唯一变量是 HTTP/2。Node 内置 `http2` 客户端在宿主复现出更低的 1.4 MB/s（比 Chrome 还慢，坐实与浏览器无关）。

## 根因

h2 下 nginx 为每请求维护 `http2_body_preread_size`（**默认 64k**）的请求体缓冲，该缓冲**同时就是向客户端通告的 HTTP/2 接收窗口**。叠加本项目 `/v1/` 的 `proxy_request_buffering off`（流式转发，本身正确），nginx 每消费转发 64k 才回一次 WINDOW_UPDATE → **吞吐 ≈ 64KB / RTT**。Docker Desktop（Windows→WSL2 NAT）RTT ≈ 45ms → 64KB/45ms ≈ 1.4 MB/s，与 Node 实测完全吻合（Chrome 用更大初始窗故稍快）。h1 无此逐窗口机制，故同端口跑 85 MB/s。

## 解决方案

443 server 加一行（`--build` 重建前端镜像方生效，dist/conf.d 是构建产物）：

```nginx

http2_body_preread_size 1m;   # 窗口 16 倍 → 吞吐不再受 RTT 钳制

```

容器内 sed 插桩 + `nginx -s reload` A/B 验证：**1.4 → 95.2 MB/s（68 倍）**；revert 回 64k 立即掉回 1.4 → 因果坐实；重建镜像后镜像内 `grep` 到指令 + 端到端复测 **85.3 MB/s**。内存安全：流式转发下该缓冲仅在下游消费慢时才填满，后端边收边写盘（63 MB/s），实际驻留远低于 1m/请求。

## 验证

容器内 sed 插桩 + `nginx -s reload` A/B 验证：**1.4 → 95.2 MB/s（68 倍）**；重建镜像后镜像内 `grep` 到指令 + 端到端复测 **85.3 MB/s**。内存安全：流式转发下该缓冲仅在下游消费慢时才填满，后端边收边写盘（63 MB/s），实际驻留远低于 1m/请求。

## 适用边界

- **指令名相近不代表用途相同——"上传"关键词差点选错指令**：`http2_chunk_size` 切的是**响应**体（默认 8k），与上传无关；`http2_body_preread_size` 才是请求体缓冲（=h2 接收窗口）。改配置前必须拉官方文档逐指令读语义，别望文生义。本例初稿错选了 `chunk_size`，靠查证才纠正。
- **"慢"先做能一刀切二分的分层压测**：直连 uvicorn / nginx-h1 / nginx-h2 / 容器内 dd 四个测点，一次跑完就把"代理/磁盘/后端/TLS"全排除，只留协议这一个变量；比在 nginx 里逐项试配置快一个数量级（同本仓"缩短链路"教训）。
- **宿主自带 curl 的 libcurl 可能不支持 `--http2`**，判 h2 别用它；用 Node `http2` 模块或看 nginx `$server_protocol` 日志。
- 与 `授权三态与离线容器.md`「全站 +130ms 底噪」、`概览页/日志下载 HTTP/2 拖到 59s」同源：Docker Desktop 的 WSL2 NAT RTT 放大会把一切"按 RTT 结算"的机制（窗口流控、连接握手）放大成数量级问题。

## 参考

- 源记录: `docs/known-pitfalls/backend/构建与开发环境.md` 「HTTP/2 大文件上传被钳到 1~4 MB/s：`http2_body_preread_size`（默认 64k）就是 h2 接收窗口，别错选 `http2_chunk_size`」
