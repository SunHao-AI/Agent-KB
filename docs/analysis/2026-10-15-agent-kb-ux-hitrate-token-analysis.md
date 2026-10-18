# Agent-KB 功能设计分析：使用者视角下的体验、命中率与 Token 成本

> 分析基线：master `9b3dce8`（2026-10-15）。全部数字为本仓实测，取证位置见文末索引。
> 使用者定义为两类：消费方 AI agent（经 MCP `kb_*` 工具检索沉淀，主要成本承受者）与人工维护者（终审、上提、治理）。

## 核心发现

| # | 发现 | 实测证据 |
| --- | --- | --- |
| 1 | 检索匹配面只有 `title+tags+summary`，正文不进匹配面 | `search.py::_parts`；`PermissionError` 仅出现在正文的条目 2 条，该类查询必然零命中 |
| 2 | 命中无相关性排序，top-K 由文件路径字典序决定 | `search.py::evaluate` 按 index.jsonl 顺序 append；query `授权` 前 5 条首位并非标题命中的条目 |
| 3 | 中文连写词仍是零命中主力（分词修复只覆盖空格分隔） | `推流` 6 命中、`死锁` 1 命中、`推流死锁` 0 命中（kb-20261015-6254 已记录） |
| 4 | 零命中返回裸 `[]`，无任何引导，agent 会直接得出"库里没有" | `kb_search` 返回 `json.dumps(rows)`，空结果与查询姿势错误不可区分 |
| 5 | `kb_get` 只有全文一种粒度，读取阶段是最大单项 token 开销 | 全文中位 1813 字 / 最长 5762 字；agent 多数场景只需要根因+方案两段 |
| 6 | `kb_search` 单次 10 条返回 5518 字，其中约 1/3 是格式化与低价值字段 | 同数据 compact 序列化 4411 字（-20%），再裁字段可再降 |
| 7 | MCP 检索无 `confidence`/`status` 过滤参数，"默认只信 verified"红线要 agent 自己事后过滤 | `mcp_server.py::kb_search` 形参仅 query/type/domain/tag/scope/limit |
| 8 | 观测闭环断粮：trace 目录与 `.kb-trace` 标记均为 gitignore 的本机临时物，139 行首日数据已丢失 | `traces/` 目录实测不存在；`trace.py` 落盘路径在 gitignore 范围 |
| 9 | 关联网络近乎空转：`related` 仅 4/197 条有值，`tags` 133/197 | `kb/index.jsonl` 实测计数 |
| 10 | 业务仓 submodule 滞后是结构性复发问题，每轮靠人肉 bump | 本次会话四仓指针齐停在 `b11c7f7`，落后主仓 29 个提交，距上次 bump 仅 1 天 |

一句话概括：三级披露、红线门控、双层检索这套骨架是对的，值得保留；当前短板集中在**检索质量层**（无排序、匹配面窄、零命中静默）和**读取粒度**（只能整篇），而这两类恰好同时伤害命中率与 token 成本——排序让 top-K 变准，命中率上升；命中变准减少试探性重复检索和整篇读取，token 下降。

## 使用者的真实旅程与漏斗

一个 agent 在业务仓遇到报错后的标准路径（AGENTS.md 规定）：

```
常驻成本            检索            判断相关性           读取全文
AGENTS.md(L1)  →  kb_search   →  读10条摘要逐条判断  →  kb_get 整篇
~1.5k 字          5.5k 字/次      (摘要截断在120字,       中位1.8k字,
                                  中位115字≈贴着上限)      最长5.8k字
```

漏斗的每一环都有流失，且流失的方式各不相同：

- 检索环节流失：查询姿势与匹配机制不匹配（中文连写、同义词、正文专名）→ 静默零命中，agent 转向"自己重新踩坑"，知识库的价值在这一环整体归零。
- 判断环节流失：无排序时 10 条命中是"抽签结果"，真正相关的条目可能排在第 11 位被 `limit` 截断；agent 需要把 10 条 5.5k 字摘要都读完才能确认哪条有用。
- 读取环节流失：判断"相关"后只能整篇读回，六段式条目里 agent 通常只要根因与方案，验证/边界两段是重复付费。

三个环节的失败模式在 trace 里本应可量化（scanned / rejected.query / rejected.filter 恒等式已经埋好了），但数据没有存活下来——这是后文"观测"一节要解决的问题。

## 体验问题

### 检索姿势知识依赖踩坑传递，而不是工具面自解释

kb-20261015-6254 这条 pitfall 的存在本身就是证据：两个业务仓的 agent 反复用 `license 授权`、`推流 fps` 这类自然查询打出零命中，得出"库没知识"的错误结论，最后靠人工把正确姿势写成知识条目。知识条目的读者恰好是最需要先知道它的群体——这是循环依赖。

工具描述（`mcp_server.py` 的 docstring）目前只有一句话，检索语义（空白分词、AND、中文连写边界、过滤器用法）没有出现在 agent 第一眼能看到的地方。MCP tool description 是每个 agent 会话都会加载的常驻文本，把三段话的检索姿势说明放进去，成本约 150 字，替代的是每个新人 agent 平均要踩一次的坑。

### 零命中与不相关共用同一个空数组

`evaluate` 已经产出了完整的死因报告（`scanned`、`rejected.filter`、`rejected.query`、逐条 matched），CLI `--zero-hit` 场景也消费过它，但 `kb_search` 返回给 agent 的只有最终数组。零命中时 agent 拿不到任何信号区分三种情况：库里真没有、查询词太长、被过滤器滤掉了。

死因报告字段已经存在，透传是零新增计算：命中为 0 时返回
`{"hits": [], "hint": "scanned 197, 全部死于整串匹配; 建议用更短的单 token(如'死锁'); 该域可用 tags: [...]"}`。
再进一步可用 `difflib` 对 title 分词做近似建议（"你是想查'推流卡顿'？"），实现成本一个函数。

### 排序缺失让 limit 变成伤害而不是保护

`limit`（MCP 默认 10）的设计意图是控制返回体积，但匹配结果按 index.jsonl 的文件名字典序排列，等于随机截断。197 条里命中 20 条时，用户拿到的 10 条由 slug 首字母决定——这个语义对使用者不可解释，也不可预期。

`matched` 里已经有 `hit_fields` 和 `hit_spans`，排序所需信息齐备：标题命中权重高于 tags 高于 summary，命中密度（span 数/token 数）次之，`confidence=verified` 与 `updated` 新近度做微调。截断从抽签变成择优后，同样的 limit 反而能支撑把它调小（见 token 一节）。

### 读取只有整篇一种粒度

条目六段式模板是为"人读全篇"设计的，agent 消费场景高度偏科：确认根因、抄解决方案是绝大多数读取的目的。实测全文中位 1813 字，而按 H2 切段后根因+方案两段通常 400–800 字。`dedup.py::h2_sections` 已经有现成的 H2 切段解析器，`kb_get(id, section="根因")` 只是把它接到读取路径上。

未指定 section 时保持现行为（整篇），指定时返回单段——增量参数，不破坏现有调用。

### 观测闭环没有持久化保障，改进循环空转

trace 是这套系统里唯一能让"命中率"从感觉变成数字的机制，它的全部数据落在 `traces/*.jsonl`，被 gitignore，`.kb-trace` 开关同样是本机临时文件。结果：写回放 spec 那天攒下 139 行，第二天目录消失；本报告想做零命中榜单，无数据可用。

trace 事件本身有红线（不含正文，只有元数据+摘要级信息），敏感度与 index.jsonl 相当，而 index.jsonl 是入库的。把 trace 数据改为入库（或每月归档提交），回填回路——`kb trace list --zero-hit` 抓出"agent 问了但没答上"的查询词，人工把对应词汇补进既有条目的 tags/summary 或立新条——才能从一次性动作变成例行机制。

### 关联与标签两条导航线接近空转

`kb_related` 依赖 front-matter `related` 字段，实测 197 条里只有 4 条填了；`tags` 覆盖 133/197。related 空转意味着"顺藤摸瓜"这条 agent 最爱的导航路径实际不存在。index.jsonl 里每条都带 `dedup_key` 和 tags，基于 tag 重合度自动产出 related 候选（人确认后写入）即可冷启动，不需要引入向量。

### submodule 滞后每轮重演

本次四仓指针还停在 `b11c7f7`（落后 29 提交），距上次 bump 提交只有 1 天。`.gitmodules` 已声明 `branch = master`，但没有任何机制在业务仓侧提醒"你的知识层落后了"。业务仓 pre-push 门禁（母本 `pre-push-gate.sh`）已经在读 git 状态，加一条 `git submodule status .agent-kb` 落后 N 个提交则 WARN 的检查是顺路的事；或者反过来在 Agent-KB 主仓 push 后对四仓发自动 bump PR。

## 命中率提升路径

按"改动成本 × 收益"排序，前三项不需要任何新依赖。

### 一、检索语义修复（针对已知零命中类型）

**中文连写**：查询侧把 CJK 连续段切成 2-gram，按覆盖率匹配而非全 AND——`推流死锁` 切出 `{推流, 流死, 死锁}`，跨词切出的 `流死` 不在库中，但 `推流`、`死锁` 都在，覆盖率 2/3 ≥ 阈值即命中。阈值建议 0.6，行为可用现有 trace 回放验收。这比引入 jieba 的分词方案便宜一个数量级（无依赖、索引体积零增长、`hit_spans` 语义只需小改），符合 followup 清单"先 spec 再动"的前置条件，spec 范围就是这一节。

**正文专名**：`PermissionError` 这类报错串、函数名、配置键是 agent 最自然的查询词，它们天然出现在正文（现象/验证段）而未必出现在 120 字摘要里。方案是给 index 记录加一个由正文派生的 `keywords` 字段（代码围栏内标识符 + H2 段名 + 高信息量 token，上限 20 个/条），`_parts` 并入匹配面。索引体积增长可控（每条约 +200 字节），检索零改动（还是 AND find）。

**同义词**：授权/license/licence、心跳/heartbeat 这类中英对照靠 aliases 解决——front-matter 加可选 `aliases: []`，index 与查询双侧展开。schema 变更走 `taxonomy.yaml` 唯一事实源的老规矩。

### 二、排序上线

如体验一节所述，`hit_fields`/`hit_spans` 已在 hand，纯打分函数 + 排序，几十行。没有排序，一切召回改进都会被 limit 截断稀释；排序是命中率改进的放大器。

### 三、零命中反馈回路制度化

trace 入库（上一节）→ 每周 `kb trace list --zero-hit` → 高频零命中词逐条消化（补 tags / 改 summary / 立新条）。这是唯一能让命中率随使用时间单调上升的机制，其余各项都是一次性修复。配套一个 `kb stat --zero-hit-report` 把消化率变成可见数字。

### 四、写入侧质量门控前移

summary 是从正文首块机械截断 120 字的派生物（中位 115 字说明几乎条条贴上限），它同时承担着 L2 相关性判断和检索匹配面两个职责，机械截断对两个职责都是损耗：判断时读到半句话，匹配时丢失正文中段词汇。允许 front-matter 显式写 `summary`（lint 校验 ≤120 字且非首块复读），agent 沉淀时由模板引导填写，人工终审时顺手打磨。`kb lint` 可以对 accepted 条目警告"summary 为机械截断"。

## Token 成本账本

消费一次知识的全链路成本与可压缩空间（字符数为实测，token 换算随分词器浮动，中文场景近似 1:1）：

| 环节 | 现状成本 | 改动 | 改动后 | 降幅 |
| --- | --- | --- | --- | --- |
| 常驻 L1（AGENTS.md） | ~1.5k 字/会话 | 不动 | 同 | — |
| kb_search 单次 | 5518 字（10 条） | compact 序列化 + 去 null | 4411 字 | -20% |
| 同上 | 同上 | 默认字段裁剪（id/title/type/domain/scope/confidence/summary/path，status/severity/updated 仅过滤时带上） | 约 3.5–3.9k 字 | 再 -12~20% |
| 同上 | 同上 | 排序上线后 MCP 默认 limit 10 → 5 | 约 1.8–2.0k 字 | 累计 -60~65% |
| kb_get | 中位 1813 字/篇 | `section` 参数，常用只取根因+方案 | 约 500–800 字 | -60% |
| 试探性重复检索 | 无法量化，零命中文化下普遍存在 | 排序+反馈回路降低"搜不到再换个词搜一次"的循环 | — | 结构性下降 |

三个注意点：

1. 字段裁剪要保守。`hit_fields` 目前没返回给 agent，反而值得**加上**——它比 summary 更快回答"为什么这条命中"。
2. limit 减半的前提是排序先行，否则只是把抽签率提高一倍，命中率损失会反噬成更多次检索，总成本不降反升。
3. 最大的 token 黑洞其实不在 kb 链路内，而是"检索失败后 agent 重新踩坑再沉淀"的整条弯路——一次死锁事故的人工排查+沉淀成本远超 kb 全链路开销。命中率与 token 两个目标在这一点上是同一个目标。

## 优先级与依赖关系

```
P0  排序(纯函数)          ──┐
P0  MCP 序列化压缩+字段裁剪  ──┼─→ limit 减半 → 检索侧 token -65%
P0  零命中 hint(透传死因)    ──┘
P1  trace 入库 + 每周回填回路 ──→ 命中率的持续机制(其余项的效果靠它验证)
P1  MCP 工具描述写入检索姿势 ──→ 新人 agent 首日即会正确查询
P1  CJK 2-gram 覆盖率匹配(先写 spec)
P2  kb_get section 参数      ──→ 读取侧 token -60%
P2  正文 keywords 入匹配面
P2  related 自动候选 + tags 覆盖治理
P3  aliases 同义词表
P3  submodule 滞后门禁提醒
```

依赖关系只有两处硬约束：limit 减半依赖排序先行；P1 反馈回路依赖 trace 入库。其余各项相互独立，可按行推进。所有改动共用同一套验收工具：`kb trace` 回放（spec 已评审）+ 现成 194 个测试 + 一条待补的"零命中→hint→改写命中"回归用例。

## 现有设计中应保留的部分

分析短板之余，以下决策经实测检验是对的，重构时应避免回退：

- **两段式检索（元数据→按需全文）** 是 token 控制的骨架，问题只出在粒度和排序，不在模式本身。
- **红线工具面强制**（draft-only、speculative 不可 accepted、scope 人工终审、单会话限额）让 agent 沉淀可以放开手跑而不污染库，197 条库存在零占位、lint 零 error 是它的成果。
- **死因报告恒等式**（filter + query + matched = scanned）把"为什么没查到"变成可审计数据，缺的只是把它接到返回值和持久化上。
- **dedup 指纹查重**在创建入口拦截重复并引导走 kb_update，返回候选 id 的失败设计优于静默新建。
- **生成物 + `index --check`** 的组合让索引漂移在 CI 可见，197 条规模下 O(N) 全量扫描也完全够用（查询 <10ms 量级），不必引入外部索引组件。

## 证据边界

本报告不含任何检索效果的历史统计：trace 首日数据（139 行）已随本机文件清理丢失，`.kb-trace` 开关也已不在位，"零命中占比""get 跟进率"两个最能定量的指标当前无数据。这正是优先级把 trace 入库排在 P1 首位的原因——上述各项改完，效果验证同样以重新积累起来的 trace 为准。

## 取证索引

| 论断 | 位置 |
| --- | --- |
| 匹配面=title+tags+summary、AND find、无排序 | [search.py](file:///d:/Workplace/Agent-KB/src/kb/search.py) `_parts` / `_hit` / `evaluate` |
| MCP 返回字段与序列化、无 confidence 过滤 | [mcp_server.py](file:///d:/Workplace/Agent-KB/src/kb/mcp_server.py) `kb_search` |
| summary=首块截断 120 字 | [entry.py](file:///d:/Workplace/Agent-KB/src/kb/entry.py) `summary()` |
| H2 切段解析器（section 参数可复用） | [dedup.py](file:///d:/Workplace/Agent-KB/src/kb/dedup.py) `h2_sections` |
| trace 落盘 gitignore、开关为临时标记 | [trace.py](file:///d:/Workplace/Agent-KB/src/kb/trace.py) `traces_dir` / `trace_enabled` |
| 双层逐层截断 | [layers.py](file:///d:/Workplace/Agent-KB/src/kb/layers.py) `search_layers_report` |
| 中文连写实测对照 | [2026-10-15-kb.md](file:///d:/Workplace/Agent-KB/kb/pitfall/tooling/2026-10-15-kb.md) 新发现节 |
| 索引规模/字段覆盖率/payload 字符数 | 本仓 `kb/index.jsonl` 脚本实测（197 条、tags 133、related 4、5518→4411） |
