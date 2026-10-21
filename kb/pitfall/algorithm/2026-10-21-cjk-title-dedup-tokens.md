---
id: kb-20261021-fefb
title: 中文标题不分词导致拉丁式多token重合判重规则静默失效
type: pitfall
domain:
- algorithm
tags:
- dedup
- cjk
- auto-reviewed
scope: stack
status: accepted
confidence: verified
created: '2026-10-21'
updated: '2026-10-21'
severity: medium
verified_by: agent
verification:
  evidence: 'Agent-KB 仓 9bca47d 实测: 第一版统一>=2token规则使 tests/test_mcp.py::test_create_duplicate_rejected(中文夹具)失败,
    分层规则后 274 passed(+6 新测试正反锁行为); 新规则下 kb search 判重词零命中且沉淀一次过闸'
  reviewed_at: '2026-10-21'
source:
  project: TencentDB-Agent-Memory
---

# 中文标题不分词导致拉丁式多token重合判重规则静默失效

## 背景 / 现象

沉淀查重门控(`kb` 仓 `gate._dup_hits`)原规则: 标题按非字母数字切成 token, 任取 3 个, 任一以子串命中既有标题即判重。该规则对英文标题尚可, 但实测误报率极高: 一次正常沉淀被 4 条不相关历史条目拦截(windows / append / jsonl 等高频词单独命中即拒), agent 被迫反复改标题绕闸。于是把规则改为"≥2 个非泛词 token 同时命中才判重"——上线即被测试夹具抓出新故障: 中文标题的重复条目全部放行, 查重对中文静默失效。

## 根因

`re.split(r"[^0-9a-z\u4e00-\u9fff]+", title)` 只把空格/标点的连续串当分隔符, 而中文书写没有空格——**一整段中文短语切出来就是 1 个 token**。于是:

- 旧规则"任一 token 命中": 一个中文长 token 靠子串匹配几乎不可能命中既有标题 → 对中文漏判; 但拉丁短词(windows/api)又到处子串命中 → 对英文误报。两头都不对。
- 直接改"≥2 token 命中": 中文标题只有 1 个 token, 永远凑不满 2 → 中文查重整体静默失效, 且无报错、测试若缺中文夹具就完全无感知。

本质: **按"词"设计的相似度规则隐含了"文本会分词"的前提**, 该前提对 CJK 不成立。要么引入真正的中文分词(jieba 等, 引入依赖), 要么按"token 信息量"分层利用"整段中文=高信息量词组"这一特性。

## 解决方案

不引入分词依赖, 按信息量分层(`kb` 仓 commit 9bca47d 内的最终规则):

1. 泛词表剔除: 平台/环境等跨主题高频词(windows/docker/api…)从判重信号中剔除, 表放唯一事实源 `taxonomy.yaml dedup.stopwords`;
2. **≥3 字中文 token 视为"词组"级信号, 单个子串命中即判重**(整段中文在标题里信息量极高);
3. 拉丁/短 token 信息量低, 需 **≥2 个同时命中**才判重;
4. 指纹(正文根因段哈希)兜底路径不受影响, 不受标题规则变动波及。

## 验证 / 参考

- 修复前第一版("统一 ≥2 token")使 MCP 中文夹具用例 `tests/test_mcp.py::test_create_duplicate_rejected` 失败(中文标题 token 恒为 1, 判重放行); 分层规则后通过, 全仓 274 passed(+6 条新测试锁行为, 含"单拉丁词不判/中文词组单命中必判"正反用例)。
- 修复后新规则实战: `kb search "分词 token 判重 查重 去重"` 与 "CJK Chinese 标题相似度 停用词" 均干净零命中(旧规则下同类查询被高频词误命中), 新条目一次通过沉淀门控。
- 通用教训: 给含中文的产品做文本相似度/查重/敏感词匹配时, 先验证"切 token"这步对 CJK 的实际产物, 再用拉丁式阈值; 测试必须配中英文双夹具, 否则中文路径静默失效无人知晓。
- 关联: `kb-20261013-4d62`(另一层"静默数据正确性"坑), 本条为其在文本匹配面的同类。
