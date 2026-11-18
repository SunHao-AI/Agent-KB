---
id: kb-20261116-d2fd
title: '出厂交付 compose 与现场编排漂移: 未兑现文档契约的 env 缺省静默降级 + 双服务卷不同源, 开发裸部署全程掩盖'
type: pitfall
domain:
- devops
tags:
- 交付compose
- 出厂模板漂移
- 环境白名单漏注入
- 缺省值静默降级
- M2M白名单为空
- 引擎鉴权bearer
- 停止任务503
- 删除任务409
- 图片卷不同源
- 取图404
- 单一宿主目录双挂载
- 裸部署掩盖
- 开发生产路径不一致
- 静态守护测试
- compose drift
- env whitelist missing
- silent default fallback
- delivery-kit compose fix
- auto-reviewed
severity: high
scope: stack
status: accepted
confidence: verified
summary: 出厂交付 compose 的 environment 是白名单——文档契约规定的引擎鉴权两键从未注入, 缺键静默落 bearer+空白名单致停止/删除任务必败;
  同族缺陷是引擎与 web 的 images 挂到两个宿主目录致取图恒 404。开发裸部署同 cwd 全程掩盖, 只有"用出厂包从零起栈"才暴露。修法——补注入两键
  + 单一宿主目录双挂载点(参数化保持向后兼容), 并用静态 YAML 守护锁形状; 活体断言另轮补。
created: '2026-11-16'
updated: '2026-11-16'
review_by: '2027-11-16'
verified_by: agent
verification:
  evidence: '复现与补丁有效性均 IT 实测: 出厂 compose 原样起栈 stop 503/delete 409 + 引擎 401、取图 404(docs/qa/evidence/20261114-e2e-a/,
    报告 §三 P1-1/P1-2); A 机 IT 副本打同款补丁后三项转绿; 出厂补丁落 setting 12c3ed7 且静态守护 tests/test_delivery_compose_d14d15.py
    6 passed、门禁 1702 passed/7 xfailed 后推 origin。活体出厂面断言按批准口径另轮补(正文已登记)。'
  reviewed_at: '2026-11-16'
source:
  project: flysee-video-setting
---

# 出厂交付 compose 与现场编排漂移: 未兑现文档契约的 env 缺省静默降级 + 双服务卷不同源, 开发裸部署全程掩盖

## 背景 / 现象

A 机全新客户全链路 E2E(2026-11-14)首次**完全按出厂交付包**(`docker/delivery-kit/docker-compose.yml`)
起栈, 一次暴露两个"开发环境永远不会遇到、客户现场必现"的缺陷:

- **D14**: 建任务正常, 但**停止任务恒 503 / 删除任务恒 409**; 引擎日志 `stop_process` 401。
- **D15**: 任务能跑出图, 但 `GET /v1/tasks/images/...` **恒 404**; 图片文件确实在宿主盘上, 只是
  web 读的目录与引擎写的目录不是同一个。

两者的共同点: 只在"用出厂 compose 从零起栈"时出现。开发机与生产裸部署(同 cwd 手工起、
env 由 shell 导出)全程走的是另一条路径, 缺陷被掩盖数年。

## 根因

1. **D14 = compose 的 `environment:` 是白名单, 文档契约写在别处**。引擎侧读的是
   `FLYSEE_AUTH_MODE` / `FLYSEE_AUTH_M2M_KEYS`, 而 `docs/deploy/secure-delivery-deployment.md`
   §4.3 早已规定"web 的 `ALGORITHM_M2M_KEY` 透传给引擎白名单"——但出厂 compose 的 engine
   env 段**从未注入这两个键**。容器 env 不是继承宿主机 shell 的, 缺键即落引擎代码缺省
   `mode=bearer` + **空白名单**, web 带 `X-M2M-Key` 的请求全部 401。缺省值"看起来能用"
   (建任务链路走另一条鉴权), 所以起栈自检与冒烟全绿。
2. **D15 = 同一份数据被两个服务各自挂载到不同宿主目录**。引擎写 `/app/images` ← 宿主
   `./data/images`, web 读 `/algorithm/images` ← 宿主 `./data/algorithm`。两个卷名各看各的都对,
   跨服务读必然 404。裸部署时两侧同 cwd 同目录, 差异被抹平。
3. **共性**: 交付模板是**入库事实源**, 但它只被"人工照抄到现场"消费过, 从未被自动化
   起栈验证过; 而契约(env 键名、挂载同源)写在**部署文档**里, 文档与模板之间没有任何
   机器可校验的连接。

## 解决方案

出厂 compose 只移植已在 IT 实跑验证过的最小补丁(setting 仓 `12c3ed7`):

```yaml
# engine.environment —— 兑现 §4.3 契约, 模式与白名单都取 web 已有的键
- FLYSEE_AUTH_MODE=${FLYSEE_ALGO_AUTH_MODE:-hybrid}
- FLYSEE_AUTH_M2M_KEYS=${ALGORITHM_M2M_KEY:-}

# backend 与 engine 的 images 改为"单一宿主目录双挂载点", 废弃独立 ./data/images 卷
- ${ALGORITHM_IMAGES_HOST_DIR:-./data/algorithm}/images:/algorithm/images   # backend
- ${ALGORITHM_IMAGES_HOST_DIR:-./data/algorithm}/images:/app/images         # engine
```

- 参数化缺省 = `./data/algorithm`, **不改 .env 时既有客户行为不变**(向后兼容的关键);
- 手册补配套: 镜像目录初始化 `mkdir -p data/algorithm/images && chmod 777`(引擎容器
  uid=1002, docker 自动建的宿主目录是 root/775 → 写侧 PermissionError), 以及起栈后
  `docker logs flysee-video-algorithm-engine | grep -F algorithm_m2m`(**期望无输出**)的探针步骤;
- **守护用静态测试而不是活体栈**(本轮经批准只做到这一层): 新
  `tests/test_delivery_compose_d14d15.py` 解析 YAML 断言两键的字面值、双挂载点存在、
  旧 `./data/images:` 已消失、`${ALGORITHM_IMAGES_HOST_DIR` 恰好出现两次。

## 验证

- **缺陷复现**: 纯容器交付栈原样起栈 → stop 503 / delete 409 + 引擎 401(D14);
  出图后取图 404(D15)。证据 `docs/qa/evidence/20261114-e2e-a/`(报告
  `docs/qa/integration-test-report-20261114.md` §三 P1-1/P1-2)。
- **补丁有效性**: A 机 IT 副本先打同款实验补丁(双备份 `.bak-preD14D15`)后 stop/delete/取图转绿。
- **出厂面守护**: `uv run --no-sync pytest tests/test_delivery_compose_d14d15.py -q` → 6 passed;
  全仓门禁 1702 passed/7 xfailed 后推 origin。
- **本次守护的真实战果**: 首次实现时把 backend 的挂载误写进 `environment:` 段, 正是
  `test_backend_mounts_images_under_algorithm_root` 立即报红——静态守护对"段落写错"这种
  纯结构错误比人眼可靠。

## 适用边界与反例

- 适用: 任何"出厂模板 + 现场照抄"的交付形态(compose/k8s manifest/ systemd unit), 特别是
  **模板里的 env 是白名单**的编排系统——漏一个键不是报错而是落缺省, 属静默失败。
- 反向风险: 静态守护只保证**形状**(键在、值字面一致、挂载点同源、旧卷不复活), 不保证
  引擎真的接受该值。活体断言(stop/delete 200、取图 200)仍要在真实起栈轮补
  (l3b B8/B12/B13 断言可复用)。
- 未做(明确登记): KEY-PARITY 自检对"白名单指纹为空 `[[]]`"目前只打 ERROR 日志不拦启动,
  是否升硬门待裁决——它是本缺陷唯一的现场可观测出口。
- 对照: 与 `kb-20261108-fc0a`(卷挂载指错/分叉导致 START_002)同族; 那条讲的是"挂载指向
  不存在的宿主目录", 本条讲的是"两侧指向不同但都存在的目录"与"env 白名单缺键"。

## 参考

- setting 仓 `docker/delivery-kit/docker-compose.yml`(根治落点)、`tests/test_delivery_compose_d14d15.py`
- `docs/deploy/secure-delivery-deployment.md` §4.3(env 契约)/§5 step 4b(起栈后探针)
- `docs/qa/integration-test-report-20261114.md` §三 P1-1/P1-2 · commit `12c3ed7`
- 关联条目: `kb-20261108-fc0a`(卷挂载缺口族) · `kb-20261012-4861`(compose 注入旧 env 名)
