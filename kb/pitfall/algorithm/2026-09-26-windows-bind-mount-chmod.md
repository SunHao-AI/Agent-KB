---
id: kb-20261013-a9c3
title: Windows bind-mount 卷上 chmod 0600 的实际语义与验证口径
type: pitfall
domain:
- algorithm
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-26'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: low
source:
  project: flysee_video_algorithm
  ref: docs/known-pitfalls/engine/烧卡交付与keyfile.md
---

# Windows bind-mount 卷上 chmod 0600 的实际语义与验证口径

## 背景 / 现象

`write_keyfile` 的 `os.chmod(path, 0o600)` 在 Windows 宿主目录 bind-mount 进
容器时不报错但**不产生 POSIX 权限位效果**（NTFS ACL 与 mode bits 只映射
只读位）；单测 `test_keyfile_perm_0600` 在 Windows 宿主直跑必 fail。

## 根因

- Linux 容器内对**容器卷/bind-mount 文件**的 chmod 走 ext4 overlay 时真实生效,

  但 Windows 卷 bind-mount（drvfs/9p）通常忽略 mode bits——0600 是尽力而为的

  纵深防御, 不是可信边界。

- keyfile 的真实防线是内容层面：只存单 key 派生子钥（非根密钥）, 泄盘影响面

  限于"该 GPU 环境该模型的 engine 缓存可解", 模型明文仍受包级 RSA/AES 分层保护。

## 解决方案

跨 OS bind-mount 上的权限位一律当"提示"不当"保证"；需要硬隔离的
密钥落盘必须叠加内容级最小权限设计（派生子钥、用途域隔离）, 权限位只是加分项。

## 验证

- 单测在 Windows 用 `@pytest.mark.skipif(os.name == "nt")` 跳过权限断言（仓内

  `test_csr_tool.py` 既有惯例）, Linux/容器内真断 `stat -c %a == 600`；

- 容器实测验收以 `docker exec ... stat -c %a /data/flysee/engine_cache/*.key` 为准,

  不要以宿主 `dir` 输出为准。

## 适用边界

跨 OS bind-mount 上的权限位一律当"提示"不当"保证"；需要硬隔离的

密钥落盘必须叠加内容级最小权限设计（派生子钥、用途域隔离）, 权限位只是加分项。

## 参考

- 源记录: `docs/known-pitfalls/engine/烧卡交付与keyfile.md` 「Windows bind-mount 卷上 chmod 0600 的实际语义与验证口径」
