---
id: kb-20261013-3c6a
title: 开发机上全量 pytest 会驱动真实 lifespan 写生产共享库：TestClient(create_app()) 的真副作用
type: pitfall
domain:
- algorithm
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-25'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: high
source:
  project: flysee_video_algorithm
  ref: docs/known-pitfalls/engine/启动对账与测试副作用.md
---

# 开发机上全量 pytest 会驱动真实 lifespan 写生产共享库：TestClient(create_app()) 的真副作用

## 背景 / 现象

**影响与处置**：本次副作用恰好是"正确修复被意外执行"，无害且证明了修复有效；
但这扇门是双向的——任何 lifespan 新增的写库/发消息操作都会在 CI/开发机上真实执行。

## 根因

`TestClient(create_app())` 会执行完整 lifespan。在开发机宿主（有 GPU、能连

共享 MySQL、`.env` 指向真实库）上，`DetectService` 初始化**成功**而非降级 None，

于是新增的 `reconcile_orphan_tasks()` 在 pytest 期间对**真实库**执行了回写。

同类先例：warmup 线程、TaskConsumer 起线程、`init_mqtt`——都在真实资源上跑过。

## 解决方案

`tests/conftest.py` 新增可复用的 `stub_lifespan_infra(mocker)`

（替身化 DetectService/init_mqtt/TaskConsumer/遥测/自检/warmup/明文清扫/信任锚/私钥判定，

只留 lifespan 编排逻辑本身）+ autouse 夹具 `_stub_lifespan_side_effects` 对三个驱动

lifespan 的测试模块（`test_api.py` / `test_startup_reconcile_orphan_tasks.py` /

`test_startup_key_source.py`）默认注入，其余模块零开销不受影响。直接 `async with

lifespan(app)` 且自带更精准 `_stub_infra` 的两个测试文件，后 patch 的精确替身仍生效

（mocker 后 patch 先生效、退出时还原为全局替身）。效果实证：全量 pytest 从数分钟

（真实 DetectService 初始化 + GPU/模型加载）降到 ~26s，且不再触碰真实 MySQL/GPU。

## 验证

效果实证：全量 pytest 从数分钟（真实 DetectService 初始化 + GPU/模型加载）降到 ~26s，且不再触碰真实 MySQL/GPU。

## 适用边界

`TestClient(app)` 的 lifespan 是真执行，不是 mock。凡是 lifespan 里

带外部副作用（写库/发消息/占显存）的逻辑，新增时必须回答"开发机全量 pytest 会发生什么"；

回答不了就做依赖注入替身。定位"谁写了这行数据"时，除了容器日志，还要查

**pytest stdout / 宿主进程日志**——写库方不一定是常驻服务。

新增驱动 lifespan 的测试模块时，把文件名加进 conftest 的 `needs_stub` 名单（或

在模块内显式调用 `stub_lifespan_infra`）。

## 参考

- 源记录: `docs/known-pitfalls/engine/启动对账与测试副作用.md` 「开发机上全量 pytest 会驱动真实 lifespan 写生产共享库：TestClient(create_app()) 的真副作用」
