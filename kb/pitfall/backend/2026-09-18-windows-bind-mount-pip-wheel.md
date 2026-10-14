---
id: kb-20261013-dc0a
title: Windows bind-mount 大文件 + pip：wheel 哈希不匹配与改名陷阱
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: probable
created: '2026-09-18'
updated: '2026-10-13'
severity: low
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/任务派发与算法联动.md
---

# Windows bind-mount 大文件 + pip：wheel 哈希不匹配与改名陷阱

## 背景 / 现象

把宿主下载的 800MB wheel 经 Docker volume（`-v D:/...:/m`）挂进容器 `pip install /m/xxx.whl`，报 `THESE PACKAGES DO NOT MATCH THE HASHES`，但宿主侧 `sha256sum` 与 PyPI 官方哈希一致；容器内对同一文件做 sha256 也能对上。

## 根因

Windows Docker Desktop 的 bind-mount（gRPC-FUSE/9p）在大文件随机读取上不稳定，

pip 边读边校验（zip 中央目录 + 分块哈希）时读到损坏字节；同一文件整体顺序读（sha256sum）反而正常，

极具迷惑性。次生坑：为省事把 wheel 改名（如 `trt86.whl`）会触发

`Invalid wheel filename (wrong number parts)`——pip 强制要求标准 wheel 命名。

## 解决方案

`docker cp` 把 wheel 拷进容器**本地盘**（`/opt/...`）再 `pip install`，保持原文件名，一次成功。

## 验证

`docker cp` 把 wheel 拷进容器**本地盘**（`/opt/...`）再 `pip install`，保持原文件名，一次成功。

## 适用边界

容器内 pip 安装宿主上的大 wheel，一律 `docker cp` 到容器本地路径，不走 Windows bind-mount；

容器内脚本（`.sh`）同理先 `sed -i 's/\r//g'` 去除 CRLF，或干脆 `docker cp` 后处理。

## 参考

- 源记录: `docs/known-pitfalls/backend/任务派发与算法联动.md` 「Windows bind-mount 大文件 + pip：wheel 哈希不匹配与改名陷阱」
