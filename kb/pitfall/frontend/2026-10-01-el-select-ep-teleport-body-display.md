---
id: kb-20261013-abd4
title: 多 el-select 页面抓错下拉：EP 下拉 teleport 到 body 平铺共存，按索引/display 判定"可见"都不可靠，误判「应用下拉为空」
type: pitfall
domain:
- frontend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-10-01'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: low
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/frontend/走查与自动化验证陷阱.md
---

# 多 el-select 页面抓错下拉：EP 下拉 teleport 到 body 平铺共存，按索引/display 判定"可见"都不可靠，误判「应用下拉为空」

## 背景 / 现象

创建任务页点「选择应用」后用 `querySelectorAll('.el-select-dropdown')` 找"display !== 'none'"的下拉读选项，读出 `[]`——疑似"应用列表为空"重大缺陷（明明有 4 个方案）。

## 根因

- Element Plus 每个 el-select 的下拉都 teleport 到 body 末尾**平铺共存**（本页 2 个 select → dropdown[0]=应用、dropdown[1]=规则），并非"最后打开的排最后"。

- 已打开的应用下拉 `style.display` 是空串（EP popper 关闭不一定写 inline display），"visible"过滤条件 `display !== 'none'` 会同时命中多个；再叠加"取最后一个非空"的启发式，实际抓到的是**选项尚未渲染的规则下拉（n=0）**，于是"空选项"是自己构造的。与「curl 参数漂移」同族：**测量工具查错目标, "缺陷"是问错了问题**。

## 解决方案

- 读下拉选项前先用 snapshot 文本对账（本例 snapshot 里 `城市道路库 5 条规则` 等 text 节点一直都在，一眼可证伪"下拉为空"）。

- 或遍历**所有** `.el-select-dropdown` 输出 `{index, item 数, 首项文本}` 再决定读哪个——一次 evaluate 全量 dump 比"猜哪个可见"快且不会错。

- 判据：**页面同时有多个 el-select 时，任何"下拉为空/选项缺失"结论必须先与 snapshot 文本交叉验证**，snapshot 没有的选项 DOM 里也不该有。

## 验证

证伪取证：snapshot 里 `城市道路库 5 条规则` 等 text 节点一直都在，一眼可证伪"下拉为空"；已打开的应用下拉 `style.display` 是空串（EP popper 关闭不一定写 inline display），"visible"过滤条件 `display !== 'none'` 会同时命中多个。

## 适用边界

本条来自 flysee_video_web 仓存量记录, 适用于该仓同类场景; 跨仓复用前先核对上下文假设是否成立。

## 参考

- 源记录: `docs/known-pitfalls/frontend/走查与自动化验证陷阱.md` 「多 el-select 页面抓错下拉：EP 下拉 teleport 到 body 平铺共存，按索引/display 判定"可见"都不可靠，误判「应用下拉为空」」
