---
id: kb-20261013-40c8
title: nginx 反代默认无 HTTP/2 与 upstream keepalive；临时插桩 `docker cp` 源配置会因 envsubst 模板而炸
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-04'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: medium
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/构建与开发环境.md
---

# nginx 反代默认无 HTTP/2 与 upstream keepalive；临时插桩 `docker cp` 源配置会因 envsubst 模板而炸

## 背景 / 现象

排查"浏览器 TTFB 远大于后端 duration"时，nginx 侧有两处默认值会真实伤性能（本次都不是根因，但都该修）；另外插桩调试时踩到一个高危操作。

## 根因

1. **`listen 443 ssl;` 不带 HTTP/2** → 浏览器 HTTP/1.1 同域 6 连接上限，页面加载的多个 API + 抓拍图在连接位上串行。nginx 1.27.5 用**新语法** `http2 on;`（1.25.1+ 起 `listen ... http2` 已废弃），经 ALPN 协商，老客户端自动降级，零兼容风险。验证看 `performance.getEntriesByType("navigation")[0].nextHopProtocol === "h2"`（宿主 `curl` 的 libcurl 可能不支持 `--http2`，别用它判胜负）。

2. **静态 `proxy_pass` 不配 `keepalive`** → nginx **每请求新建一条到 backend 的 TCP**（用完即关）。修法三件套，缺一条就静默无效：

   ```nginx

   upstream flysee_backend { server backend:17998; keepalive 32; keepalive_timeout 4s; }

   # location 内：

   proxy_pass http://flysee_backend;

   proxy_http_version 1.1;

   proxy_set_header Connection "";   # 不写这行, nginx 仍发 Connection: close, 池子完全不复用

   ```

   **`keepalive_timeout` 必须小于上游的空闲超时**：uvicorn 未显式设 `--timeout-keep-alive` 时**默认仅 5s**；nginx 池若设 60s，会复用一条后端已静默关闭的连接 → GET 偶发延迟重试、**POST 直接 502**（nginx 默认不重试非幂等请求）。取 4s 让 nginx 永远先关，竞态窗口为零。验证：连打 25 次 POST 看是否全 200。

3. **`docker cp` 源 `nginx.conf` 进容器 = 高危**：`/etc/nginx/conf.d/default.conf` 是**渲染产物**，源文件里的 `${FLYSEE_TLS_PUBLIC_PORT}` 尚未替换。cp 源文件覆盖后 `nginx -t` 直接 `unknown "flysee_tls_public_port" variable`；若此时 `-t` 因别的原因先失败而没 reload，容器仍在跑内存里的旧配置，容易误判"没事"。恢复用 `up -d --force-recreate frontend`（重跑 envsubst），不是 `restart`。临时插桩要 cp 就 cp **渲染后的**配置（先 `docker cp` 容器→本地，改完再 cp 回去）。

## 解决方案

"改进有效"不等于"命中根因"：h2 与 keepalive 都让某些数字变好（首轮 getInfo 602→237ms），但**底噪没动**，说明不是它。判断要盯住那个恒定不变的底噪数字，而不是"整体感觉快了"。真凶见 `backend/授权三态与离线容器.md`「全站 /v1 固定 +130ms 底噪」条。

## 验证

"改进有效"不等于"命中根因"：h2 与 keepalive 都让某些数字变好（首轮 getInfo 602→237ms），但**底噪没动**，说明不是它。

## 适用边界

"改进有效"不等于"命中根因"：h2 与 keepalive 都让某些数字变好（首轮 getInfo 602→237ms），但**底噪没动**，说明不是它。判断要盯住那个恒定不变的底噪数字，而不是"整体感觉快了"。真凶见 `backend/授权三态与离线容器.md`「全站 /v1 固定 +130ms 底噪」条。

## 参考

- 源记录: `docs/known-pitfalls/backend/构建与开发环境.md` 「nginx 反代默认无 HTTP/2 与 upstream keepalive；临时插桩 `docker cp` 源配置会因 envsubst 模板而炸」
