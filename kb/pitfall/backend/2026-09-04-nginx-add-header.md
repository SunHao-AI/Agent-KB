---
id: kb-20261013-ebeb
title: nginx 全部响应零安全头 + add_header 继承陷阱（子块一个 add_header 屏蔽父块全部）
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

# nginx 全部响应零安全头 + add_header 继承陷阱（子块一个 add_header 屏蔽父块全部）

## 背景 / 现象

第七轮浏览器测试用 `curl -D -` 逐类响应核查：`index.html`、`/static/*`、`/v1/*` **全部零安全响应头**（无 XFO / nosniff / Referrer-Policy / HSTS）。本系统是内网管理台（任务控制、授权管理），clickjacking 与 MIME 混淆面不为零。

## 根因

nginx `add_header` 的继承规则是全有或全无：子 location 只要写了任意一条 `add_header`，server 级全部 `add_header` 即被整体屏蔽而非叠加。本前端有 6 个 location 自带 `Cache-Control`，只在 server 级 include 安全头片段，恰好这 6 类响应独缺安全头且无任何告警；此前基线更是从未配置过安全头。

## 解决方案

新增 `security-headers.conf` 片段（XFO=DENY、nosniff、Referrer-Policy=SOWCO、HSTS），`Dockerfile.prod` COPY 到 `/etc/nginx/snippets/`：

1. **nginx `add_header` 继承是"全有或全无"**：子级（location）只要写了**任意一条** `add_header`，就**完全屏蔽**父级（server）的**全部** `add_header`——不是叠加。本前端有 6 个 location 自带 `Cache-Control`（/media/、/static/、/assets/、sw 三件套、= /index.html、SPA 回退），只挂 server 级的话这 6 类响应独缺安全头且毫无报错。**正确模式：片段文件 + server 级 include 一次 + 每个自带 add_header 的 location 再 include 一次**。（`/v1/` 的 no-store 由后端中间件下发、location 本身没写 add_header，server 级正常覆盖到。）

2. **dev 自签环境 HSTS 只给 `max-age=60`**：长 max-age（如 31536000）会把浏览器**锁死**在该 host 强制 https——换 http 调试端口（15173 直连排障）会被浏览器强跳回 443 且清不掉；生产部署层再覆盖为 `max-age>=31536000; includeSubDomains`。XFO=DENY 前置核查：本域零 iframe 嵌入自身页面功能（InnerLink/iframeViews 均空、init SQL 无内嵌本前端的外链菜单）——**加安全头前必须先查"是否会破坏既有功能"**，有内嵌需求就改 CSP `frame-ancestors` 白名单。

## 验证

curl 三类响应全带 4 头；带自有 Cache-Control 的 /static/ 正确"长缓存 + 安全头"共存；`always` 使 404 响应也出头；页面功能零回归（dashboard/任务页/console 无异常）。注意 dev 里 curl 到 `127.0.0.1:15443` 的 HSTS 不会生效锁死（浏览器只对**受信证书**执行 HSTS，自签被忽略——这是 dev 环境的第二层保护）。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/backend/构建与开发环境.md` 「nginx 全部响应零安全头 + add_header 继承陷阱（子块一个 add_header 屏蔽父块全部）」
