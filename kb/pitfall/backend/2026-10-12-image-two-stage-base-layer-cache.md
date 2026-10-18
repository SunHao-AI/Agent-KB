---
id: kb-20261012-7cf8
title: 'engine 镜像两段式拆分(依赖层 base 镜像 + 秒级代码层): 层缓存失效导致改一行代码重下 2.5GB+ 的根治方案'
type: pitfall
domain:
- backend
tags:
- docker-layer-cache
- base-image
- build-time
- bom
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-09-25'
updated: '2026-10-13'
review_by: '2027-04-11'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/性能与容错优化.md
---

# engine 镜像两段式拆分(依赖层 base 镜像 + 秒级代码层): 层缓存失效导致改一行代码重下 2.5GB+ 的根治方案

## 背景 / 现象

**日期**: 2026-09-24 (engine 仓 `Dockerfile.full` / `Dockerfile.trt86` / `scripts\build-engine.ps1`)

**现象**: 单文件 Dockerfile.trt86 里 apt + TRT wheel(781MB) + torch cu118(857MB) + 服务依赖 + cudnn 门禁(696MB) 全是网络重依赖层。BuildKit 层缓存一旦失效(换 daemon/prune/上层指令变更), 日常只改 `app/` 代码也会触发 >2.5GB 全量重下, 实测单次 >1h, 且 `download-r2.pytorch.org` 连续两次 ReadTimeout 直接构建失败。

## 根因

BuildKit 层缓存是按指令文本派生键的优化而非契约, 换 daemon, prune, 上层指令文本变更都会使其后所有层失效; 单文件 Dockerfile 把 apt + TRT wheel + torch 等 >2.5GB 网络重依赖与高频变动的代码层混排, 缓存一旦失效, 只改一行代码也触发全量重下.

## 解决方案

**解决**(两段式 + tar 归档):
- 拆 `Dockerfile.full`(全部重依赖, 产出 `flysee-video-algorithm-base-trt86:<日期tag>`)与 `Dockerfile.trt86`(日常入口: `ARG BASE_IMAGE=<base>` + `FROM` + `COPY` 代码, 秒级)。base 层含 cudnn 门禁, `docker save` 归档 `.imagecache\*.tar`(已 gitignore+dockerignore)。
- `build-engine.ps1` 编排: 默认日常构建(base 缺失自动 `docker load` 归档 tar); `-Full` 仅在依赖清单变更时重建 base 并 save。实测: `-Full` 一次 16min(大部分层仍命中本机缓存), 日常全流程(build+up) **82s**, 原全量 >1h。
- torch 层加 `--find-links https://mirrors.aliyun.com/pytorch-wheels/cu118/` 优先 + 官方索引回退 + `--timeout 120 --retries 5`(阿里云镜像实测有 torch 2.4.1+cu118 与 torchvision 0.19.1+cu118 全量 wheel)。

## 验证

原文实测: `-Full` 一次 16min(大部分层命中本机缓存), 日常全流程(build+up) 82s, 原全量 >1h; 并实录 download-r2.pytorch.org 连续两次 ReadTimeout 直接构建失败。

## 适用边界与反例

**关键陷阱**:
- **旧 Dockerfile 不能只注释掉 pip 层**——BuildKit 按指令文本匹配缓存, 改层文本会使其后**所有层**失效, "删掉重装层"反而更慢; 正确做法是把代码层抽成以 `FROM base` 开头的新 Dockerfile。
- **base 与代码层版本漂移**: base tag 必须显式钉死在 `Dockerfile.trt86` 的 `ARG BASE_IMAGE` 默认值里, 依赖变更时同步升 tag, 否则会静默用旧依赖出"新"镜像。
- **编辑工具重写 `.ps1` 会静默丢 BOM**(复发): 重写后必须字节校验补 `EF BB BF`, 否则 PS 5.1 按 ANSI 解码炸中文。
- 运行镜像的 `HEALTHCHECK/CMD/ENV(PYTHONPATH)` 归代码层, 纯链接器变量(`LD_LIBRARY_PATH`)归 base 层——按"变动频率"而非逻辑归属划分层。

**通用教训**: 含 GB 级下载的重镜像, **把"变与不变"物理拆成两个 Dockerfile** 比依赖层缓存可靠——层缓存是优化不是契约(daemon 更换/prune/上层文本变更都会丢), tar 归档的 base 镜像才是可携带的确定性缓存。`docker commit` 方案不可取(容器运行态污染 + 与实例绑定), 要用 Dockerfile 正式产 base。

> 原始单文件已并入本文件归档（2026-09-25 新增「推流 ffmpeg stdin 同步写被 RTMP 背压永久挂起：写线程隔离+限时看门狗+stderr 落盘」）。

## 参考

- 源记录: `docs/known-pitfalls/backend/性能与容错优化.md`
