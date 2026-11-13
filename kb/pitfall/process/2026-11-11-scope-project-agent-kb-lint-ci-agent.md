---
id: kb-20261111-c872
title: 沉淀门控硬编码 scope=project 与 Agent-KB 仓 lint 位置规则互斥，本仓新建条目必使 CI 变红且 Agent 无法自修
type: pitfall
domain:
- process
tags:
- kb-gate
- scope-ownership
- lint-position-rule
- ci-red
- generated-entry
- promotion-workflow
- 沉淀门控
- 归属权终审
- 位置校验规则
- 门禁互斥
- 上提流程
- draft-exemption
- lint-warning-severity
- draft豁免
- 警告降级
- auto-reviewed
scope: stack
status: accepted
confidence: verified
created: '2026-11-11'
updated: '2026-11-11'
severity: medium
review_by: '2027-11-11'
revision:
  reason: content-edited
  from_status: accepted
  at: '2026-11-11'
verified_by: agent
verification:
  evidence: '2026-11-11 方案1落地实测: Temp沙箱 draft+project 条目 kb lint --scope agent-kb
    报 warning 前缀 exit0, 同条目翻 accepted 报 error exit1; tests/test_lint.py 新增 draft仅warning/proposed+accepted+deprecated仍error
    两用例, 全量 426 passed; 消费面 cli.py warns分流 与 bootstrap.py doctor仅error计FAIL 零改动天然兼容;
    本条目自身经 update_entry 追加后 lint exit0(唯一H1校验通过)'
  reviewed_at: '2026-11-11'
---

# 沉淀门控硬编码 scope=project 与 Agent-KB 仓 lint 位置规则互斥，本仓新建条目必使 CI 变红且 Agent 无法自修

## 背景 / 现象

Agent-KB 的沉淀门控规定：Agent 新建条目只可能得到 `scope: project`（`kb new --generated`
与 MCP `kb_create` 硬编码，CLI 还会提示 "generated entries are always scope=project"），
且红线 #2 禁止 Agent 改 `scope`——上提只能"建议"，由人 `kb set-scope` / `kb export` 落地。

而本仓 CI 跑的是 `kb lint --scope agent-kb`（`.github/workflows/kb-ci.yml`），其中一条规则：

```
kb-20261111-8c02: scope=project must not live in agent-kb
```

于是在 **Agent-KB 仓内**让 Agent 沉淀任何一条知识，产物必然让 CI 变红，且 Agent 自己
无法修好——改 scope 越红线，删条目丢知识。2026-11-11 实际踩中：`kb new` 建
`kb-20261111-8c02` → 自审 accepted → `kb lint --scope agent-kb` exit 1。

## 根因

两条不变量分别由两个模块各自成立，交叉处无人负责：

- `gate.create_draft()`：`scope="project"` 硬编码，写入口层防越权（合理，业务仓场景成立）；
- `lint.py`：`scope == "project" and scope_arg == "agent-kb"` → 报错（合理，Agent-KB 仓
  是通用知识载体，不该混项目私有知识）。

单看都自洽，但"Agent 能否在 Agent-KB 仓内直接沉淀"这个组合态没被任何一方定义：
门控假设 Agent 永远在业务仓（docs 载体）沉淀，lint 假设本仓条目全是人审过的 stack/universal。
缺的是**第三个环节**——Agent 产物在本仓的"待上提暂存区"语义（如 `status: draft` 豁免 scope 校验）。

## 解决方案

三选一（2026-11-11 已按第 1 条落地, 见下方"新发现"；此前按第 3 条人工兜底）：

1. **lint 给 draft 豁免**：`scope=project` 且 `status=draft` 时降级为 warning——Agent 产物
   天然是待审暂存态，终审（`set-scope`）落地前不该算违规。改动最小，语义最顺。
2. **门控区分仓型**：`create_draft` 检测目标仓是否 Agent-KB 本体，是则允许
   `scope=stack` 起步（仍由人终审），代价是削弱"Agent 永不定 scope"这条简单红线。
3. **人工兜底**（方案 1 落地前的过渡做法）：Agent 建完立刻 `kb promote` 建议，由人跑 `kb set-scope <id> stack`。
   能解红，但把 CI 绿不绿押在"人记得补一刀"上，Agent 单独跑完任务的会话一定留红。

无论选哪种，**不要把 lint 规则放宽成"允许 project 常驻 agent-kb"**——那会让项目私有知识
真的沉淀进通用仓，破坏两处知识分层的初衷。

## 验证

- 复现（2026-11-11 本机）：`kb new pitfall --generated --repo .` 建条目 →
  `kb lint --scope agent-kb --repo .` → exit 1，输出仅上述一行；`kb index --check` 同期 up to date，
  证明失败来自 scope 规则而非索引漂移。
- 消除：`kb set-scope <id> stack --repo .` 后 `kb lint --scope agent-kb` exit 0、
  `index --check` 无漂移（`kb-20261111-8c02` 实测前后对比）。
- 规则位置：`src/kb/lint.py` 的 `must not live in agent-kb` 分支；
  门控侧 `src/kb/gate.py::create_draft`（`scope="project"`）与 `src/kb/cli.py` 的 note 提示。

## 适用边界与反例

- 只影响**在 Agent-KB 仓内**直接沉淀；业务仓（`--repo docs`，`lint --scope project`）方向相反
  （`scope!=project must be promoted`），Agent 产物天然合规，无此冲突。
- 不是"Agent 该不该有写权限"的问题：draft/speculative 起步、状态可自审 accepted 都正常工作，
  卡点只在 scope 一个字段。
- 与 lint 的其他 scope 规则（`scope!=project` 必须待在 agent-kb 侧）成对，只动一边会打开
  反向漏洞——真要改，两条需同时按"暂存态"语义重写。

## 新发现(2026-11-11): 方案 1 已落地并实测

同日经批准落地**方案 1(lint 给 draft 豁免)**: `src/kb/lint.py` 对
`scope=project && status=draft` 的该规则改报 `warning: ` 前缀消息, proposed 及以上仍是
error。消费面零改动——CLI `kb lint`(warns/hard 分流, 退出码只看 hard)与 `kb doctor`
(仅 error 计 FAIL)早已按 `warning: ` 前缀约定处理, MCP 面无独立 lint 消费者。

实测证据:
- Temp 沙箱仓 draft+project 条目: `kb lint --scope agent-kb` →
  `warning: ... (draft 暂存待终审)`, exit 0; 同条目翻成 accepted → error, exit 1;
- 单测两条新增(draft 仅 warning / proposed+accepted+deprecated 循环仍 error),
  全量 426 passed;
- 本坑自此降为"已修复缺口": 修复前 Agent 在本仓沉淀需人工 `kb set-scope` 兜底
  (方案 3, 本条目自身的实际执行路径); 修复后 draft 暂存态可停留本仓待审不使 CI 变红,
  终审(人工 set-scope)仍照常。

## 参考

- `src/kb/gate.py::create_draft`（scope 硬编码处）、`src/kb/lint.py`（成对的两条 scope 位置规则）
- `.github/workflows/kb-ci.yml`（`kb lint --scope agent-kb` 为 CI 门禁）
- AGENTS.md 红线 #2（Agent 永不改 scope）与 #1（可自审 accepted）
