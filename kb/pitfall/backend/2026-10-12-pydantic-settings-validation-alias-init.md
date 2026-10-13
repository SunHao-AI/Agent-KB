---
id: kb-20261012-f349
title: pydantic-settings validation_alias 下按字段名传构造参数被静默丢弃
type: pitfall
domain:
- backend
tags:
- pydantic-settings
- validation-alias
- config
scope: stack
status: accepted
severity: medium
confidence: verified
created: '2026-10-11'
updated: '2026-10-12'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/Pydantic数据校验.md
---

# pydantic-settings validation_alias 下按字段名传构造参数被静默丢弃

## 背景 / 现象

> 面向：**任何**嵌套 settings 字段带 `validation_alias` 且未开 `populate_by_name`、`extra="ignore"` 的 pydantic-settings v2 仓（本例：`flysee_video_algorithm` P0 C1 测试编写时实测，2026-10-11）。

**现象**：测试里 `AivisDbSettings(password="x"*32)` / `WebSettings(m2m_key="x"*32)` 看似正常构造，实际字段落回默认值（`"<dev-default>"` / `""`），且**不抛任何错**。prod 弱值校验器上线时，若测试照这种写法，"prod + 弱值应拒绝"的用例会因为值根本没落到字段上而假绿/假红都说不清。

## 根因

**根因**：`password: str = Field("<dev-default>", validation_alias="FLYSEE_MYSQL_PASSWORD")` + `model_config extra="ignore"`，未开 `populate_by_name`。pydantic v2 下 init 关键字 `password` 既不匹配字段期望键（alias）也不匹配 alias，落入 extra 被 `extra="ignore"` 静默吞掉。

## 解决方案

**方案**：构造时用 **alias 同名关键字**：`AivisDbSettings(FLYSEE_MYSQL_PASSWORD="x"*32)`（alias 同时是 init 期望键）。

## 验证

哨兵技巧即验证：正向用例 `test_prod_all_strong_passes` 存在且 GREEN ——若 alias 传参失效字段回落弱默认，正向用例会被校验器误杀，GREEN 本身就证明值真实落位（原文「要点」段）。

## 适用边界与反例

**要点**：
- 判定口诀：**带 `validation_alias` 且没开 `populate_by_name`，构造/`model_validate` 就得用 alias 名**，字段名会被静默忽略。
- 哨兵技巧：让"全部合法值也应通过"的正向用例存在（如 `test_prod_all_strong_passes`），若 alias 传参失效字段回落弱默认，正向用例会被校验器误杀——GREEN 本身就证明值真实落位。
- `env_ignore_empty` 只作用于 env/dotenv 源，不影响 init kwargs；`secret_key=""` 能原样抵达 after-validator。

## 参考

- 源记录: `docs/known-pitfalls/backend/Pydantic数据校验.md`
