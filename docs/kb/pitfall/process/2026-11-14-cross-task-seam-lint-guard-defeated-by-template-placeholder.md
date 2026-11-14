---
id: kb-20261114-a0bb
title: '跨任务接缝: lint 按''键不存在''判缺失 × 模板注入空串占位, 守护线被自己的默认值永久屏蔽'
type: pitfall
domain:
- process
tags:
- auto-reviewed
scope: project
status: accepted
confidence: verified
created: '2026-11-14'
updated: '2026-11-14'
severity: high
summary: 'spec 未定义''缺失''的义项, 两个任务各自补全: lint 实现成键不存在才告警, 另一任务给全部模板加 summary 空串占位, 合起来照模板建档的条目永不触发守护。两任务各自评审均通过,
  缺陷只在整分支评审暴露; 修法是按值判缺失并用端到端探针替代单元断言'
review_by: '2027-11-14'
verified_by: agent
verification:
  evidence: 'lint_repo 四例探针前后对照实测(2026-11-14): 修复前 created=2026-11-20 且 summary 键不存在
    → 告警, 同日期 summary="" → 不告警(盲区), 两例 created=2026-11-01 均豁免; 判据改为按值后第 2 例转为告警、其余三例不变。代码出处
    src/kb/lint.py:123; 对应测试改写为 tests/test_lint.py::test_lint_summary_empty_value_counts_as_missing
    并补存量空串豁免用例; 全量 517 passed、lint --scope agent-kb --strict 退 0'
  reviewed_at: '2026-11-14'
---

# 跨任务接缝: lint 按'键不存在'判缺失 × 模板注入空串占位, 守护线被自己的默认值永久屏蔽

## 背景 / 现象

一个 9 任务计划要给知识库条目加"L2 结论摘要"渐进守护：
- **T4** 在 `lint.py` 加规则——"缺 `summary` 就告警"，新条目判界、存量豁免；
- **T8** 按 spec §3.4 给全部 8 个模板的 front-matter 加 `summary: ""` 占位。

两个任务**各自评审均 Approved**，全量测试 517 passed，`index --check` 绿。
最终全分支评审才发现：这条守护线**对任何照模板建档的条目永远不会触发**。

四例探针实测（`lint_repo` 直调，同一 fixture 只差 summary 键形态）：

| created | summary 键 | 期望 | 实际 |
| --- | --- | --- | --- |
| 11-20（新） | 无键 | 告警 | 告警 ✅ |
| 11-20（新） | `summary: ""` | 告警 | **不告警 ❌** |
| 11-01（旧） | 无键 | 豁免 | 豁免 ✅ |
| 11-01（旧） | `summary: ""` | 豁免 | 豁免 ✅ |

第 2 行就是盲区，而模板产出的条目**天然**长成第 2 行。

## 根因

**spec 把"缺失"定义成了一个多义词，两个任务各自补全了不同的义项。**

spec 只有一处相关表述，且是给取值语义写的：`Entry.summary()` 判断"strip 后非空才采信，
空 = 缺失（回落正文派生）"。它对 **lint 该不该把空串算缺失**没有任何裁决。于是：

- T4 读作"空串是模板占位，是**已声明**状态，不该骚扰用户"→ 实现成 `if "summary" not in fm`；
  还为这个理解写了测试 `test_lint_summary_present_and_empty_exempt`（断言空串**不**告警）；
- T8 读 spec §3.4 的字面"模板加 `summary: ""` 占位"→ 照做。

两边都自洽、都有测试、都过评审。**评审单位是任务，而缺陷住在任务之间**——
T4 的评审员看不到还没落地的模板，T8 的评审员看不到 lint 的判据写法。

放大因素还有第二条接缝：`kb new` / MCP `kb_create` 不传 summary 时**不写键**（不是写空串），
所以 agent 主路径有守护，人工模板路径没有 → 团队里"谁会被守护"取决于建档姿势，
这种不对称比全员失效更难被发现。

## 解决方案

**判据改按值，不按键**，让"空 = 缺失"在全链只有一种含义：

```python
s = str(e.fm.get("summary") or "").strip()
if not s:
    if str(e.fm.get("created", "")) >= SUMMARY_REQUIRED_SINCE:
        errors.append(f"warning: {rid}: 缺 summary(...)")
elif len(s) < 10:
    errors.append(f"warning: {rid}: summary 仅 {len(s)} 字符, ...")
```

模板的 `summary: ""` **保留不动**——它是填写提示，人填了自然不报；schema 仍放行空串
（占位与人工清空合法）。三处语义随即同形：`entry.py` 取值、`lint.py` 判缺失、
`query.stat` 计显式覆盖率，全用 `str(x or "").strip()`。

**流程侧（比代码更重要）**：

1. 一个术语被**两处以上**消费时，spec 必须逐处写明义项，或显式声明"未定义，由实现决定"
   并把该决定升为待评审项；
2. 单任务评审无法覆盖接缝，**多任务计划在收口时必须有一次整分支评审**，
   且问题清单要显式包含"跨任务一致性"，否则评审员默认只看 diff 局部；
3. 写**端到端探针**而不是单元断言：用"系统真实产出的那条数据"（模板建出来的条目）
   过一遍完整规则链。单元断言只证明规则实现了实现者的理解，不证明理解符合意图。

## 验证

- 修复后同一探针第 2 行由"不告警"转"告警"，其余三行不变；
- 改写的测试
  `tests/test_lint.py::test_lint_summary_present_and_empty_exempt` →
  `test_lint_summary_empty_value_counts_as_missing`，并补"存量空串仍豁免"用例锁住边界；
- spec §3.3 补写口径裁决（含判界字段取 `created` 而非初稿 `updated` 的理由——按 `updated`
  会让存量条目因一次错别字修订就冒告警，与"存量不追"冲突）；
- 全量 517 passed，`kb lint --scope agent-kb --strict` 退 0，`index --check` 绿。

## 适用边界与反例

- **成立**：一条规则被多个模块/多次提交共同实现，且判据依赖某个**自然语言术语**
  （"缺失""已填写""有效""活跃"）。这类词几乎总有"键不存在 / 值为空 / 值无效"三义。
- **警惕信号**：某任务给全量对象注入占位默认值，而另一任务按"有没有"判定该类对象。
  这两件事同时存在时，守护几乎必然被自己的默认值屏蔽。
- **不适用**：判据本就该区分"未填"与"清空"（如用户显式清空要尊重、未填要提示），
  此时按键判是对的——但那必须在 spec 里写明是**有意**区分，且端到端探针要覆盖两种姿势。
- 反过来也别把"键存在即合规"当万能解：本例若删模板占位来迁就 lint，等于为了迁就
  一个错误的判据牺牲更好的产品默认值。**先定语义，再选判据**。

## 参考

- 修复提交: 本仓 `fix(lint): summary 缺失按值判, 不再被模板空串占位屏蔽(终审 F1/F2)`
- 事实源: `docs/superpowers/specs/2026-11-14-l2-summary-federation-contract-design.md` §3.3
  （已补落地口径修正段）
- 最终评审报告: `.superpowers/sdd/2026-11-14-l2-summary-federation-contract/final-review-report.md`
