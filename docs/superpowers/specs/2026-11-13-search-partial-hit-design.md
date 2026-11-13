# 检索部分命中降级(AND-first + Partial Fallback)设计

- 日期: 2026-11-13
- 状态: 待审阅
- 范围: 仅 `src/kb/search.py` 匹配策略与 trace 埋点字段; 不含会话观测(B 阶段另立 spec)

## 1. 背景与根因

hit_rate 连续下滑: W42 50.9% → W44 50.3% → W45 38.7% → W46 35.1%
(有效检索口径, 剔 not_executed 与合成 caller, 数据源 traces/*.jsonl 全量 1461 条)。

根因量化(同一数据回放):

| query token 数 | n | hit_rate |
| --- | --- | --- |
| 1 | 556 | 77.7% |
| 2 | 199 | 46.2% |
| 3 | 257 | 19.1% |
| 4 | 235 | 8.5% |
| 5 | 127 | 6.3% |
| 6+ | 79 | 5.1% |

`_hit`([search.py](../../src/kb/search.py)) 对空格切分的 token 做**全 AND 子串匹配**,
任一 token 在 title/tags/keywords/summary/sections 拼出的 haystack 中缺位即整条拒。
Agent 日益倾向描述式长查询(4+ token 占有效检索约 31%), 几乎全部死在 AND 硬拒上。
中文侧已有 2-gram 覆盖率兜底(`_CJK_COVERAGE=0.6`), 不是本次主因。

次要信号(不在本次修复范围, 记录备查): 含中文 query hit_rate 33.1% vs 纯英文 63.6%,
与红线 3b(tag 语言与查询语言须一致)一致, 属条目侧沉淀问题。

## 2. 方案概述(已选: AND 优先 + 部分命中降级)

严格 AND 有任何结果 → 行为逐字节不变。仅当 AND 零结果且 tokens ≥2 时, 降级为
部分命中: 至少命中 `min(2, len(tokens))` 个 token 的条目按命中比例分档纳入结果。

否决项: 彻底软评分(改变全部多 token 查询的结果集, 回归面不可控); MCP 侧零命中
重试(一次调用多条 trace 事件, 聚合口径复杂化, 延迟翻倍)。

## 3. 详细设计

### 3.1 `_hit` 返回值扩展

`_hit(parts, tokens) -> (fields, spans, hit_tokens)`:

- 全命中: `hit_tokens == set(tokens)`, 与现行为一致;
- 部分命中: 返回已命中 token 的 fields/spans(逐 token 独立计算, 现有循环天然支持);
- 零命中: `([], [], set())`。

`_token_spans` 不动。`evaluate` 主循环单次遍历内完成, 不重复扫 haystack。

### 3.2 `evaluate` 降级分支

```
第一遍: 严格 AND(现逻辑), 收集 and_hits
if and_hits 或 无 tokens: 走现路径, 结果与排序逐字节不变
else:
    第二遍候选 = 第一遍中 hit_tokens 非空的条目(不重扫)
    门槛: len(hit_tokens) >= min(2, len(set(tokens)))
    排序键: (-round(len(hit_tokens)/len(set(tokens)), 6), -score, index)
    其中 score = _score(rec, fields, spans, hit_tokens, today)  # 复用现有打分
```

- 分档在前保证 3/4 命中稳定排在 1/4 命中前, 同档内沿用 `_score` 字段权重体系,
  不引入新常数;
- `tokens` 含重复词时按 `set(tokens)` 计, 与 `_score` 的 `n_tok` 口径一致;
- 单 token 查询永不降级(无 AND 可放宽, 命不中就是命不中)。

### 3.3 报告与埋点

- `report` 新增 `match_mode: "and" | "partial"`(无 query 时缺省不写);
- partial 时 `report["partial"] = {"min_hit": k, "tokens": n}`, 且
  `rejected.query` 记"降级后仍零命中"的条目数(部分命中的条目计入 matched);
- 恒等式保持: `rejected.filter + rejected.query + len(matched) == scanned`;
- trace search 事件透传 `match_mode`(search→trace 上报路径加一个键),
  聚合层 hit_rate/consume_rate 口径**不变**(returned 非空即命中);
- 面板不改: feed 只读固定字段, 多一键无破坏; 后续如需展示 partial 另行处理。

### 3.4 错误处理

无新增失败模式: 索引缺失、limit≤0 契约、净化路径均不动。`_hit` 第三元素为
新返回值, 所有调用点(仅 evaluate 一处 + 单测)同步更新。

## 4. 测试与验收

1. **单测**: `_hit` 三态(全/部分/零命中); 降级触发条件(AND 有结果不降级;
   单 token 不降级; 1/4 命中被 min_hit=2 拒); 排序(比例档优先、同档 score 序、
   同分 index 序); `match_mode` 与恒等式; 现有 search 相关单测全绿。
2. **离线回放**(验收门槛): 脚本读 traces 历史有效 query, 对**当前** index.jsonl
   重放(新旧两种策略各跑一遍再对比——索引自查询当日有演进, 只与"同索引下的
   旧策略结果"比, 不与 trace 里记录的历史 returned 比):
   - 旧策略(纯 AND)命中的查询, 新策略结果集与排序 100% 不变;
   - W46 口径回放 hit_rate 35.1% → ≥50%;
   - 全量有效查询回放 hit_rate 显著提升且无原命中回退。
3. `kb lint --scope agent-kb` 通过; `kb index --check` 通过。

## 5. 明确不做

- 不引入中文分词器, 不调 `_CJK_COVERAGE`;
- 不改 MCP/CLI 参数签名与返回结构(除新增可选键);
- 不动索引构建(index.jsonl 字段不变);
- 不做 B 阶段会话级 trace 关联(独立 spec);
- 不改聚合口径(hit_rate 定义不变)。
