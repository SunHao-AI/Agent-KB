---
id: kb-20261012-d3e8
title: 跨服务契约字段名错配：上游"提简版"，下游读"完整版"（通用探针）
type: pitfall
domain:
- backend
tags:
- cross-repo
- contract
- redis
- queue
scope: universal
status: accepted
severity: high
confidence: probable
created: '2026-09-04'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/Pydantic数据校验.md
---

# 跨服务契约字段名错配：上游"提简版"，下游读"完整版"（通用探针）

## 背景 / 现象

> 面向：`flysee_video_web` × `flysee_video_algorithm`（链路：web `POST /v1/tasks` → redis rpush → algo `lpop` 消费）。修 [web backend/services/task_service.py#L36-64](file:///d:/WorkPlace/Pycharm/flysee_video_web/backend/services/task_service.py#L36-64)。

**现象**：`POST /v1/tasks` 收到 200 + 新 task_id，web 端 INSERT `aivis_tasks` status=pending 成功；redis `LLEN task:dispatch` 从 1 → 0，**铁证**表示 algo `TaskConsumer._consume` 已 lpop 消费；但 algo 日志里 `DetectService.start` 入口后立刻返回 `{status:"error", message:"未找到模型配置 (rule_classes.models.first_model)"}`——status 永卡 pending（**即使 GPU/模型都在**）。

## 根因

**根因**：

1. 前端 [views/tasks/create.vue](file:///d:/WorkPlace/Pycharm/flysee_video_web/frontend/src/views/tasks/create.vue) 表单字段只有 `app_id` / `rules[]` / `input` / `output` / `width` / `height` / `bitrate` / `frame_ignore` / `osd` / `report`——**没有 rule_classes**。前端 `api/task.js::createTask` 把表单里**非标准字段**解构到 `task_data["extra"]`（Pydantic `TaskCreate` 上 `extra` 字段）。
2. 算法侧 [app/services/detect_service.py#L177-274](file:///d:/WorkPlace/Pycharm/flysee_video_algorithm/app/services/detect_service.py#L177-L274) 的 `_extract_model_name` 注释明确写 `task_data["rule_classes"][0]["models"]["first_model"]["model_name"]`（design spec `2026-08-07-db-unify-migration-design.md` 与算法注释一致）。
3. web `task_service.py::create_task` 早期版本**完全没读** `algorithm_suites.rules`，只看前端给的 `rules: list[str]`（rule_id 字符串数组）→ 直接 `rpush` → 算法拿到一份**没模型名字 + 没类别 + 没权重路径**的精简 task_data → `_extract_model_name` KeyError → DetectService.start 失败 → status 卡 pending。
4. 这类 bug **只有 redis 链路真跑通后才会暴露**（HTTP 200 + redis 消费 + 双端日志都"看起来 OK"——form 只缺模型配置那块）。

**为什么不是直接加 `rule_classes` 到 `TaskCreate` 顶层**：

- 让前端**只发 rule_id** 而模型/类别/权重列表由 web 后端从 `algorithm_suites.rules` **抽取并补全**——这符合单一事实源原则（model 配置的真相在 setting 仓的 `model_cache` 表 + web 仓的 `algorithm_suites.rules` JSON，前端只挑规则引用，不应该再生一份权重路径）。
- 算法侧仍保持 `task_data["rule_classes"]` 单一入口（不拆成 web 字段 + 算法字段两种 view），**未来算法加新字段只改算法 + web service 这一端**，不是链路两端都动。

## 解决方案

**解决**：

- web `task_service.py` 加 `_resolve_rule_classes(suite_id, rule_ids)`：
  1. 从 `algorithm_suites.rules`（JSON 列）读全量规则列表；
  2. 如 `rule_ids` 为空，返回全量；否则用 `set(rule_ids)` 过滤，只保 `rule.get("rule_id") in wanted` 的项；
  3. 返回**完整规则项**（含 `models` / `first_model` / `second_model` / `classes` / `weight_path` 等算法侧要的全部字段）。
- 在 `create_task` 里 `task_data["rule_classes"] = self._resolve_rule_classes(data.app_id, data.rules)`——**加在标准字段**（非 extra），`data.extra` 若显式带了 `rule_classes` 仍可覆盖（单向便利，`extra` 后处理总优先级更高）。
- 算法侧**不动**：保持 `_extract_model_name` 的实现，避免反向耦合 web 的"补充规则"规则；契约仍由算法侧 anchor（消费者是算法，只算法侧能定义"我需要哪几个字段"）。

## 验证

<!-- 待补: 原始记录未含验证步骤 -->

## 适用边界与反例

**预防**：

- 跨服务契约**字段名必须 grep 双端**。算法侧 `_extract_model_name` 看 `task_data["rule_classes"][0]...`，web 侧 `create_task` 必须**同 commit 引入** `task_data["rule_classes"]`——**不要"上游先发布改造、下游后跟进"** 这种时序。
- **HTTP 200 ≠ 链路对**：跨服务数据传递 + 异步队列（redis / rabbitmq）的 E2E，必须验**消费端的真实入口日志**（本例：`DetectService.start` 的 `[START] {task_id, app_id, ...}` 字典打印），不能只看 `LLEN` 减 1 就以为算法"跑起来了"。
- **status 卡 pending 排查顺序**：先看 `aivis_tasks.status` 是否动过（pending 没动过 = 进程没起来，**不动不是链路慢**）→ 然后看算法侧日志 `[START]` 一行后立刻 `status:"error"` 的**新字段名**（如"未找到模型配置"就是契约字段错配）→ 最后才怀疑 GPU / 模型 / 输入流不在线。
- **单端探测法**：永远从**靠近消费者的那一侧**定位（算法侧的 `[START]` 后的 error message），不要先在 web 侧加 log——web 侧只验证"对端是不是消费到了"（redis LLEN + task_id 匹配），更不能代吃消费端职责。

## 参考

- 源记录: `docs/known-pitfalls/backend/Pydantic数据校验.md`
