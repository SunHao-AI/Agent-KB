# 门控自助化设计: 编辑范围放宽 + 文档口径纠偏

- 日期: 2026-11-05
- 范围: `src/kb/gate.py`、`src/kb/mcp_server.py`、`AGENTS.md`(Agent-KB 仓) + 四个业务仓 `AGENTS.md` 的沉淀协议措辞
- 不在范围: `set_scope()` / `export_entry()`(共享库上提保持人工独占)、`create_draft()` 的 draft 上限、状态机 `_TRANSITIONS`

## 1. 问题

用户反馈"人工限制过于麻烦, 建议允许 Agent 自行处理"。实测走查后发现, 体感与实际约束错位:

| 操作 | AGENTS.md 口径 | 实现事实 |
| --- | --- | --- |
| `kb review` 状态流转 | "人工 CLI 专属" | MCP `kb_review` 已暴露, CLI 有 `--as-agent`, accepted 强制 `evidence` |
| confidence 提升 | "人工复核后手改为 verified" | `--to accepted --confidence verified` 一步生效, 手改文件反而违规 |
| `kb_update` 编辑范围 | 仅 draft | 确实硬拦(`update_draft`), proposed/accepted 不可改 |
| `set-scope` / `export` | 人工 | 确实人工独占(无 `by` 参数, `export` 带 `src.unlink()` 破坏性搬移) |
| 自审 accepted | 单会话 ≤3 条 | `AUTO_ACCEPT_CAP = 3` 按 server 实例计数 |

真正卡住 Agent 的只有三处: 编辑范围、会话终审上限、以及**文档口径过时导致的误操作**(实测: 有人按文档去手改 confidence, 被门禁拒绝, 误判为"流程死锁")。

## 2. 设计

### 2.1 `update_draft` → 按 status 分支的 `update_entry`

删除现有的 `status != "draft"` 单一硬拦, 改为:

| status | 行为 |
| --- | --- |
| `draft` | 全量可改(不变) |
| `proposed` | 全量可改, `status` 不动 |
| `accepted` | 允许改, 但**自动降级** `accepted → proposed` |
| `deprecated` / `superseded` | 仍拒(终态不可逆, 与 `_TRANSITIONS` 一致) |

降级时的字段处理:

- `status` → `proposed`
- 移除 `verified_by`、`verification`, 并从 `tags` 去掉 `auto-reviewed`(它们记录的是"当时通过终审的证据", 结论已变, 留着会误导事后抽查)
- 写入 `fm["revision"] = {"reason": "content-edited", "from_status": "accepted", "at": "<YYYY-MM-DD>"}` 留审计痕迹
- `review_by` 不动; 重审通过再 accepted 时由 `review()` 既有分支刷新到期日

`_reindex(repo)` 已在函数末尾, 无需额外处理。降级不改所属池(`build_indexes` 只把
`status == "draft"` 归 draft 池, proposed/accepted 同属 live 池), 但 `title`/`body`/`tags`
是索引列, 重建仍是必须的(§44 既有理由)。

`schema/frontmatter.schema.json` 未设 `additionalProperties: false`, 新增 `revision` 不触发 lint 违规。

### 2.2 会话终审上限: 只放开"终审存量"

`AUTO_ACCEPT_CAP` 的意图是防 Agent 刷噪音。刷噪音的入口是**新建**, 不是**终审已有条目**。因此:

- `create_draft` 侧不变: 单次任务最多沉淀 3 条(红线 #5 的约定)
- `kb_review --to accepted` 去掉 `auto_accepted` 计数与 `AUTO_ACCEPT_CAP` 常量, 保留全部硬约束: 必须带 `evidence`、必须把 confidence 提升为 verified/probable、打 `auto-reviewed` + `verified_by: agent` 留痕、到期进 `due_review`

效果: 清理存量 backlog 不再被切成多个会话; 新建沉淀仍有节流。

### 2.3 文档口径纠偏

- **Agent-KB `AGENTS.md`**: 沉淀门控红线第 1 条改写为"Agent 可自主终审状态(draft→proposed→accepted), accepted 必须附 `evidence` 并提升 confidence"; 补上 `kb review <id> --to accepted --confidence verified --evidence "..."` 的完整示例, 明确**不需要也不允许手改 front-matter**; 红线第 5 条区分"沉淀 3 条上限"与"终审不限次"; 新增"已终审条目被编辑会自动降级重审"的说明。
- **四个业务仓 `AGENTS.md`**(`flysee-video-setting` / `flysee_video_web` / `flysee_video_algorithm` / `flysee_media_server`)的沉淀协议第 6 条: 删除"人工复核后将 confidence 改为 probable/verified"这类读起来要手改文件的措辞, 改为 `--confidence`/`--evidence` 参数化流程, 并说明 Agent 可自行终审。

## 3. 兜底机制(放宽后靠什么不失控)

1. accepted 必须带 `evidence`, 写入 `verification.evidence` 留痕
2. Agent 自审打 `auto-reviewed` 标签 + `verified_by: agent`, `kb stat` 可筛
3. 编辑 accepted 自动降级 + `revision` 审计字段
4. `REVIEW_CYCLE_DAYS = 365` 到期复核清单
5. `set-scope`/`export` 人工独占不变 → 共享库(Agent-KB)污染面为零, 放宽只影响本项目库

## 4. 测试

`tests/test_gate_write.py`(现有 12 处 agent 自审相关用例)新增:

- `update_entry` 改 draft → 成功, status 仍 draft
- 改 proposed → 成功, status 仍 proposed
- 改 accepted → 成功且 status 变 proposed, `verified_by`/`verification` 已清, `tags` 无 `auto-reviewed`, `revision.from_status == "accepted"`
- 改 deprecated / superseded → `GateViolation`
- `kb review --to accepted` 第 4 次不再被上限拒绝(去掉 `AUTO_ACCEPT_CAP` 的回归)
- MCP `kb_update` 面走同一分支(工具名不变, docstring 改写)

`tests/test_mcp.py` 更新 `kb_update` 拒绝已终审条目的旧断言。

## 5. 验收

```powershell
cd D:\WorkPlace\Pycharm\Agent-KB
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m kb.cli lint --scope agent-kb --repo .
```

在 `flysee-video-setting` 实测一次闭环: 对已 accepted 条目调 `kb_update` 补 tags → 确认返回 status=proposed 且带 `revision`, `kb search` 不再命中该条(退回 draft 池), `kb index --check` 不 stale。

## 6. 已否决的替代方案

- **只追加不改写**(新正文必须以旧正文为前缀): 更严格, 但红线 #3b 要求追加"新发现"时同步补 tags 并可能调整既有段落顺序, 前缀约束会在正常维护路径上误伤。改用"改了就降级重审"——同样防止 accepted 结论被静默改写, 且不阻塞编辑。
- **保留旧证据进 `verification_history`**: 多一层结构, 但 `auto-reviewed` + git 历史已可回溯, YAGNI。
- **两个上限都提到固定值(如 20)**: 阈值仍是拍脑袋, 且没解决"清理存量 backlog 被切会话"的真实痛点。
- **放开 `set-scope`/`export`**: 跨仓破坏性搬移 + 污染所有项目共享的 Agent-KB 库, 风险与收益不对称, 保持人工。
