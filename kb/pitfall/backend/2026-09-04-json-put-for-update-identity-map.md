---
id: kb-20261013-4d62
title: JSON 整列读-改-写无行锁：并发 PUT 全报 200 但后提交者整段覆盖先提交者（丢失更新），且加了 FOR UPDATE 还可能被 identity
  map 旧快照废掉
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
severity: high
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/ORM与测试可移植性.md
---

# JSON 整列读-改-写无行锁：并发 PUT 全报 200 但后提交者整段覆盖先提交者（丢失更新），且加了 FOR UPDATE 还可能被 identity map 旧快照废掉

## 背景 / 现象

5 个线程各开独立 Session 并发 upsert **互不相同**的 rule（同 suite），全部返回成功、无任何报错；读回 `rules` 列发现 4/5 条的 `rule_name` 回到了旧值——只有最后提交者写的（连同它自己快照里的其它 4 条旧值）存活。**接口全绿、数据静默丢失**，前端单用户操作永远复现不了。

## 根因

1. **无锁读-改-写**：`apply_rules_batch` 是 `SELECT suite → 内存里基于 suite.rules 重建整个数组 → suite.rules = cur → commit`。MySQL RR/RC 下普通 SELECT 是快照读，5 个事务都读到同一份旧数组，各自只改自己那条再**整列覆盖写回**——典型的 lost update。JSON 列把"多行并发"降维成了"单行整列覆盖"，行级并发保护完全不生效。

2. **identity map 废锁**（修复一线 `with_for_update()` 后仍复现才挖出）：若同一 Session 更早做过 plain SELECT（中间层前置校验/日志很常见），ORM identity map 已缓存该实体；SQLAlchemy 默认 `Query` 执行锁定读后**不刷新已加载对象的属性**（`populate_existing` 才会）——锁拿到了、数据库层串行化了，但内存里仍拿旧快照重建数组，锁形同虚设。

## 解决方案

```python

suite = (

    db.query(AlgorithmSuiteModel)

    .populate_existing()          # 锁读必须穿透 identity map 旧快照

    .filter(AlgorithmSuiteModel.suite_id == suite_id)

    .with_for_update()            # SELECT ... FOR UPDATE, 同 suite 变更串行化

    .first()

)

```

容器内实测：修复前 5 并发 4 丢失 → 修复后两个场景（裸并发 / 每线程先 plain SELECT 再进 batch）均 **0 丢失**；`test_rules_batch.py` 29/29 无回归（sqlite 方言自动忽略 FOR UPDATE，测试不受影响）。

## 验证

容器内实测：修复前 5 并发 4 丢失 → 修复后两个场景（裸并发 / 每线程先 plain SELECT 再进 batch）均 **0 丢失**；`test_rules_batch.py` 29/29 无回归（sqlite 方言自动忽略 FOR UPDATE，测试不受影响）。

## 适用边界

- **凡"整列读-改-写"（JSON 列聚合、counter、配置 blob）必须 `SELECT ... FOR UPDATE`（或乐观版本列）**；"每行一条记录"的关系表天然有行锁保护，改成 JSON 数组就把并发问题隐藏掉了——评审时对 `xx.json = [dict(r) for r in ...]` 模式必须问"并发写怎么办"。

- **`with_for_update()` 所在 Query 必须配 `populate_existing()`**，否则同 Session 早前的普通读会让锁失效；或者严格约束"锁读之前不得有任何对该实体的读"。

## 参考

- 源记录: `docs/known-pitfalls/backend/ORM与测试可移植性.md` 「JSON 整列读-改-写无行锁：并发 PUT 全报 200 但后提交者整段覆盖先提交者（丢失更新），且加了 FOR UPDATE 还可能被 identity map 旧快照废掉」
