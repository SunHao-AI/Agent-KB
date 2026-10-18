---
id: kb-20261012-a767
title: 泛化到全部"字段默认值污染"PUT 接口：即使复用 POST 模型也必须加 `_UNSET` 哨兵（DictType / Client PUT）
type: pitfall
domain:
- backend
tags:
- pydantic
- put
- dict-type
- sentinel
scope: stack
status: accepted
severity: high
confidence: verified
created: '2026-09-07'
updated: '2026-10-12'
review_by: '2027-04-10'
source:
  project: flysee-video-setting
  ref: docs/known-pitfalls/backend/Pydantic数据校验.md
---

# 泛化到全部"字段默认值污染"PUT 接口：即使复用 POST 模型也必须加 `_UNSET` 哨兵（DictType / Client PUT）

## 背景 / 现象

> 面向：`flysee-video-setting` 全部仍存在**默认值污染风险**的 PUT 端点。上一节修 `RoleUpdate` / `MenuUpdate` 是「复用 POST 模型」的典型；本节记录的是**表面上独立模型但字段带默认值**的另一类，加上同族的「API 层直接用裸 `data: dict` 绕过全部 Pydantic 校验」的兜底模式。

**现象**（本轮 #5 #6 修复前）：

1. **`PUT /v1/system/dicts/types/{code}`**：复用 `DictType`（POST 模型），`status: int = 1`。
   - 用户想只改名字，不提交 `status`：Pydantic 会给默认 `1` → provider `payload.get("status", 1)` 拿到 1 → **库内 `status` 从真实值（0）被强制改写为 1**。用户没有做任何"启用"操作，字典类型就被默默打开。
   - 更少见的连锁：不提交 `dictKey` 也会因必填触发 422；即不写新的 dict_key 也无法改名——**跟 Menu 复用 Model 类一个道理**。

2. **`PUT /v1/clients/{client_id}`**：**直接 `data: dict`**——完全无 Pydantic 模型，无字段级校验，mass assignment 风险全部依赖 service 白名单。
   - 未提交键 vs 显式 null vs 空串（`""`）**三种语义无法在 API 层区分**——全靠前端避免空串，防御薄弱。
   - 前端某天传 `{"name": ""}` 就会把 `name` 写空（DB 层 `name NOT NULL`，SQLite 违约 500，MySQL 报 1048）；传 `{"app_key": "..."}` 若绕过 service 白名单也可被落库——**字段级校验全在 service**，API 层 5xx 表面上 OK，但语义层已经失控。

## 根因

**根因**（三类抽象）：
1. **默认值污染**：Pydantic `Field(default=N)` 未提交字段也会被 N 占位；上了 `exclude_unset` 能剔除，但**当默认值就是业务默认（`status=1`）**时，`exclude_unset` 剔除后 provider 拿不到 key → 需要 presence check 才能「未提交真不动」。
2. **复用 POST 模型**：POST 语义 = 全量必填；PUT 语义 = 局部可选。同一模型无法同时承载两个语义，**必须拆开**并各自用哨兵或 exclude_unset。
3. **纯 `dict` 端点**：无 Schema = 无字段默认值污染但也无字段级校验；前端任何字段名写错 → service 层白名单不认识 → **静默丢弃**，比 422 更隐蔽。

**为什么 exclude_unset 不够**（延续上一节的结论，且在本 bug 上更锋利）：
- `DictType.status: int = 1` 未提交时 `model_dump(exclude_unset=True)` 会把 `status` 从 payload 剔除（好）；但 pydantic v2 里，同一字段 `default=1` + **显式传 1** 都会走 `exclude_unset` 保留分支。**区分「未提交」与「显式传 1」在本例不 bump 出任何问题**——都必然写 1。**provider 要判存在才写**才能承载「显式传 0 vs 未提交」两个动作。

## 解决方案

**解决**（并施）：

*API 层*——引入 `_UNSET` 哨兵（与上一节 `RoleUpdate`/`MenuUpdate` 同款）：

```python
_UNSET = object()

class DictTypeUpdate(BaseModel):
    dictName: str | None = Field(default=_UNSET, min_length=1, max_length=64)
    dictKey:  str | None = Field(default=_UNSET, min_length=1, max_length=64)
    status:   int | None = Field(default=_UNSET)

# 客户端（原本 data: dict）也升到独立 Schema：
class UpdateClientRequest(BaseModel):
    name: str | None          = Field(default=_UNSET, min_length=1, max_length=128)
    dept_id: int | None       = Field(default=_UNSET)
    dept_name: str | None     = Field(default=_UNSET, max_length=128)
    status: str | None        = Field(default=_UNSET, max_length=16)
    expires_at: datetime | None = Field(default=_UNSET)
    last_seen_url: str | None = Field(default=_UNSET, max_length=512)

# 路由层：presence-based 组装 payload + 语义归一
payload = {py: v for cn, py in mapping.items() if (v := getattr(body, cn)) is not _UNSET}
if not payload: return ApiResponse(code=400, msg="请至少提交一个要修改的字段")
# NOT NULL 列：显式 null → 拒（api 层 return 400）
if "name" in payload and payload["name"] is None:
    return ApiResponse(code=400, msg="name 不能为空")
# 业务归一：dept_id null → 0（未选择）
if "dept_id" in payload and payload["dept_id"] is None:
    payload["dept_id"] = 0
```

*Provider 层*——逐字段 presence check + 唯一性约束：

```python
# save_dict_type · UPDATE 分支
if "dict_name" in payload:
    if not payload["dict_name"]:
        raise_auth("AUTH_400", field="dict_name")
    t.dict_name = payload["dict_name"]
if "dict_key" in payload:
    if not payload["dict_key"]:
        raise_auth("AUTH_400", field="dict_key")
    # 改 dict_key 需查唯一性（排除自身）——创建分支原本就有，update 分支也补齐
    dup = db.execute(
        select(SysDictType).where(
            SysDictType.dict_key == payload["dict_key"],
            SysDictType.dict_code != t.dict_code,
            SysDictType.is_del == 0,
        )
    ).scalar_one_or_none()
    if dup:
        raise_auth("AUTH_409", resource="dict_key")
    t.dict_key = payload["dict_key"]
if "status" in payload:
    t.status = int(payload["status"])
```

*附带修 create 分支的原始 bug*（本轮测试用例会先撞到这里）：
- `save_dict_type(code=None, payload)` 里 `payload["dict_code"]` 是 KeyError——因为 API 端根本没传 `dict_code`（provider 用 `_next_code("D")` 生成）。**创建分支应当由后端生成 dict_code**（无前端入参），删掉对该 payload key 的引用。

## 验证

回归测试 `tests/test_system_dict_client_partial_update.py` 5 条 dict_type + 5 条 client 用例（原文「预防」段指认：`partial_<field>_only` + `<not_null_field>_explicit_null_400`）。

## 适用边界与反例

**语义契约**（前端/测试同款）：
- **未提交键**：provider/service 不动该列。
- **显式 `null`**：
  - NOT NULL 列（`dict_name` / `dict_key` / `client.name` / `client.status`）→ API 层 400（不允许清空 NOT NULL）。
  - **业务有 null 语义**：`client.dept_id: null → 0`（0=未选择）；`client.expires_at: null → 永久授权`；`client.dept_name: null → ""`（保持字符串非空列）。
- **显式 `0` / `""` / 显式数字**：写值（`status: 0` ็บ 关）。
- **空 payload**：API 层 `return ApiResponse(code=400, msg="请至少提交一个要修改的字段")`——避免 provider 空 UPDATE 浪费 refresh + 语意歧义。

**预防**（清单）：
- **任何新 PUT 端点**：`grep frontend` 找到表单提交是否有「只改单字段」的场景；若有，必用 `_UNSET` 哨兵（**不是** `exclude_unset`）。
- **发现裸 `data: dict` 端点**：升级成 Pydantic 模型 + `_UNSET` 默认；即使 service 有白名单，也要在 API 层加字段级校验（**双重防御**）。
- **provider 层**：`<field> = payload.get(<key>, <fallback>)` 是危险写法；要么改成 `if "<key>" in payload: <field> = payload[<key>]`，要么改用 `model_dump` 前先明确记录"哪些 key 未提交"。
- **Unicode-ready 检查**：Provider 里凡涉及"业务默认 ≠ 未提交"的字段（`status`/`is_default`/`visible` 等 bool-型 int），一律 presence check；**默认值只在 create 分支保留**。
- **测试首推两条**：`partial_<field>_only`（其他字段保留原值）+ `<not_null_field>_explicit_null_400`（拒清空 NOT NULL）——详见 `tests/test_system_dict_client_partial_update.py` 5 条 dict_type + 5 条 client 用例。

## 参考

- 源记录: `docs/known-pitfalls/backend/Pydantic数据校验.md`
