---
id: kb-20261023-358e
title: '环境变量开关用子串匹配: notdemo 反而启用了 demo'
type: pitfall
domain:
- security
tags:
- auto-reviewed
scope: project
status: accepted
confidence: verified
created: '2026-10-23'
updated: '2026-10-23'
severity: medium
review_by: '2027-10-23'
verified_by: agent
verification:
  evidence: '探针修复前后对账: 修复前 KB_SOURCES=notdemo/nodemo_nowiki 均意外装配 demo; 修复后 9 组取值(正反例+大小写/空白/未知token)全符期望,
    limit 四路(0/-1/abc/1)命中数与后端调用次数符契约; test_sources.py +2, pytest 329 全绿, ruff F,E9
    通过'
  reviewed_at: '2026-10-23'
---

# 环境变量开关用子串匹配: notdemo 反而启用了 demo

## 背景 / 现象

`kb` 的外接源装配(`sources.build_connectors`)按 `KB_SOURCES` 环境变量决定启用
哪些连接器, 实现是 `if "demo" in wanted: out.append(DemoConnector())`——对整串
做**子串**匹配。第三十三轮走查探针实测: `KB_SOURCES=notdemo` 或
`nodemo_nowiki`(用户意图明确是"不要 demo")反而**启用**了 demo, 外部内容混进
agent 的联邦检索结果。`build_connectors` 的 `only` 参数同样中招。

## 根因

`in` 运算符对 str 是子串包含、对 set/list 才是成员判断——两种语义共用一个符号,
写"名单开关"的人脑子里想的是后者、手滑写出前者。触发条件又极其日常: 任何包含
`demo` 三个字母的取值(`notdemo`、`demo_disabled`、甚至 `xdemo`)都会翻转成
"启用"。这类开关的**故障方向不对称**: 意外开启外接源会把外部内容注入检索结果
(轻则污染, 重则注入), 而"意外关闭"最多是没数据——开关误判的代价天平时偏向
"多开"这一侧, 所以必须精确匹配。

同轮附带发现同一函数的 limit 契约拧巴: `max(1, min(limit, 20))` 把 `limit=0/-1`
抬成 1(向远程后端真发一次请求), 再由 `[:limit]` 截成空——结果碰巧对, 但语义
是错的且白耗一次网络往返。"结果对、路径错"也是契约缺陷, 它会在下一次重构时
咬人。

## 解决方案

- 开关值按逗号切分成 token 集合后**精确成员判断**
  (`tokens = {t.strip() for t in wanted.split(",") if t.strip()}`), 保留
  lower 后的大小写不敏感与空白容忍; 未知 token 静默忽略(前向兼容新版本
  连接器名)。
- `search(limit)` 契约归一: `limit <= 0` 直接返回空且不触后端; 非数值回退
  默认值。上限 20 在 `_search` 调用处生效, 不再与"抬下限"混在一个表达式里。
- 全仓 grep 确认无其他子串开关(`in wanted` 同款指纹仅此一处)。
- 回归 2 个: 装配精确匹配(反例 notdemo/nodemo_nowiki + 正例大小写/空白/未知
  token 不回退)/ limit 契约(≤0 不触后端、非数值不炸、上限对齐)。

## 验证

探针修复前 `KB_SOURCES=notdemo → 装配=['demo']`(两处反例全中); 修复后 9 组
取值(含正反例与边界)全部符合期望, limit 四路(0/-1/'abc'/1)命中数与后端
调用次数均符合契约。pytest **329 全绿**(327+2), ruff `--select F,E9` 通过。

## 适用边界与反例

适用于所有"名单型配置"(环境变量/配置字段取逗号分隔或多值列表判断启用项):
**判据: `in` 的左操作数若是一个"名字", 右操作数必须是集合而不是拼好的字符串**。
反例: 语义上确实要子串匹配的场景(日志过滤、模糊搜索)不在此列——区别在于
"名单"有明确的分隔符与词表, 有分隔符就必须先切开再判断, 从不例外。凡是
"开关误开的代价远大于误关"的名单(外接源、feature flag、权限位), 都值得在
装配函数入口多花一行切分成本。

## 新发现(第三十八轮 §56: limit 契约洞在检索漏斗重现, 且故障形态升级为"误导性自解释")

同族 limit 契约缺陷在**双层检索漏斗**(`layers.search_layers_report`, MCP
kb_search 与 CLI search 共用)重现, 且比 §51 的"结果对路径错"更糟: 旧实现
`take = max(0, limit - len(out))` 让 `limit<=0` 时每层取 0 条**却照常扫全库
生成死因报告**, MCP 零命中分支据此产出 `"scanned 1: 死于过滤器 0, 死于词
匹配 0; 建议用更短单 token 重试"`——hint 数据自洽地撒谎(两个死因都是 0 却
建议改词), 把 agent 引向"改写查询"的错误自救, 真相是 limit=0 根本没给名额。
**带自解释的输出会放大上游契约缺陷**: 消费方把上游的"空"翻译成一套因果
故事时, 上游必须先如实区分"没查到"与"没去查"。

修复: 漏斗处 `int()` 归一(非数值回退 10, 上限 100), `limit<=0` 截零短路且
report 全零(不触后端); MCP 面零名额直接返回"名额为零, 未执行检索"的如实
hint, 不进死因分析分支。MCP JSONSchema 的 `int` 不拒负数、JSON 允许小数,
类型校验层拦不住值域, **数值参数的值域契约只能由被调方自己守**——这与
§52"入口拒收"同理, 只是对象从类型换成值域。

## 参考

`src/kb/sources.py` `build_connectors`/`SourceConnector.search`(第三十三轮修复)、
`src/kb/layers.py` search_layers_report + `src/kb/mcp_server.py` kb_search
limit 归一(第三十八轮 §56)、
走查记录 `docs/tests/2026-10-21-full-coverage-test.md` §51/§56; 同族:
kb-20261022-6fd6(判据全仓普查方法, 本轮修复半径确认即用它)。
