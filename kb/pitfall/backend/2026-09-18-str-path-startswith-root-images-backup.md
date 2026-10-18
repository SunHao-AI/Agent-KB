---
id: kb-20261013-e8e1
title: 「文件在目录内」用 `str(path).startswith(str(root))` 判定：字符串前缀 ≠ 路径段包含，兄弟目录 `images_backup`
  越界读/`rmtree` 递归删
type: pitfall
domain:
- backend
tags: []
scope: stack
status: accepted
confidence: verified
created: '2026-09-18'
updated: '2026-10-13'
review_by: '2027-04-11'
severity: high
source:
  project: flysee_video_web
  ref: docs/known-pitfalls/backend/任务派发与算法联动.md
---

# 「文件在目录内」用 `str(path).startswith(str(root))` 判定：字符串前缀 ≠ 路径段包含，兄弟目录 `images_backup` 越界读/`rmtree` 递归删

## 背景 / 现象

`GET /v1/tasks/images/{filename:path}` 的防护是「resolve 后必须仍在 images 根内」，但实现写成：

```python

if not str(full_path).startswith(str(images_root)) or not full_path.is_file():

    raise NotFoundError("图片不存在")

```

`<root>/images_backup/secret.jpg` 解析后的字符串同样以 `<root>/images` 开头——**兄弟目录被误判"在目录内"**。`filename:path` 完全由请求方控制，任何登录用户传 `images_backup/xxx` 即可越界读取 images 根外、与之共享父目录的任意文件（同挂 `ALGORITHM_ROOT` 卷的模型缓存、配置、其它业务目录都前缀可达即泄露）。同一错误原语在 `task_service.py` 共 5 处：图片读取、file:// 输入校验 ×2、**删除守护 ×2**——后两处失守的后果不是"多读"而是 `shutil.rmtree` **递归删兄弟目录**（当前被上游 `_parse_file_input` 拦 `..` + uuid 生成的 task_id 兜住不可达，属"防护原语错误、靠调用方运气"）。容器 E2E 实证修复前兄弟目录文件可读；单测 `test_image_sibling_dir_prefix_collision_rejected` 修复前 `DID NOT RAISE`。

## 根因

1. **`str.startswith` 是「字符前缀」，路径包含是「段前缀」**——两者只在 root 恰不以完整段边界对齐时才有区别，所以单测「合法文件放行 + `../` 穿越拒绝」两类经典用例全绿也暴露不了（穿越被 resolve 拦、合法在根内两种语义都碰不到碰撞带）。缺陷带恰在 root 与兄弟目录的命名重叠处。

2. **一个错误原语被复制成防护惯例**：图片读取先写错，file:// 校验、删除守护"照图片同款防穿越"复制粘贴，5 处同错——错误的原语比没有原语更危险，因为它给审查者「这里有防穿越」的强烈既视感（D21「其余两角有防护的观感」同款盲区）。

3. **下载端点测试全 mock service 层**：`test_task_image_cache_headers.py` 用 `mocker.patch(...get_task_image_file)` 只测缓存头，真实边界判定零覆盖——防线本体在 mock 阴影里。

## 解决方案

- 新增统一原语 `TaskService._path_within(root, target, *, strict=False)`：resolve 后用 `Path.is_relative_to`（Python 3.9+，项目 3.10）做**段包含**判定；`strict=True` 额外拒绝 `target == root`，供两处删除守护使用——防 `task_id`/`upload_id` 异常时目标退化为根目录自身被整根 `rmtree`（原 `startswith` 连这层也没有）。

- 5 处调用点全部替换（读取/校验用默认、删除守护用 `strict=True`）；同错族一次收口，杜绝"改一处漏四处"。

- 新增 3 单测（兄弟目录碰撞拒绝[红→绿]/合法放行/`../` 穿越不回归）+ `_path_within` 语义单测；定向 33 passed，全量 **586 passed, 1 skipped**。容器 E2E 6/6：真实算法卷造 `images_d27probe/` 兄弟目录，越界读 404、合法图 200、清理无残留。

- 日志下载端点（`glob` 固定模式 + 登录鉴权）与签发侧 exports（签名通道 + fail-closed）走查健康。

## 验证

新增 3 单测（兄弟目录碰撞拒绝[红→绿]/合法放行/`../` 穿越不回归）+ `_path_within` 语义单测；定向 33 passed，全量 **586 passed, 1 skipped**。容器 E2E 6/6：真实算法卷造 `images_d27probe/` 兄弟目录，越界读 404、合法图 200、清理无残留。

## 适用边界

- **路径包含判定只有两种正确写法**：`Path.is_relative_to(root)`（py3.9+）或 `os.path.commonpath`；`str(path).startswith(str(root))` 一律视为缺陷，无论有没有"resolve 过了"。走查口诀：**resolve 拦的是 `..`，拦不了兄弟目录**——审防穿越代码时必造一个 `<root 名>_x` 兄弟目录探针。
- **删除类守护要比读取类多一层「target ≠ root」**：读取越界泄露是读一个文件，`rmtree` 守护失守是毁整棵树；`strict` 语义（段包含且非自身）是删除守护的最低标准，即使当前输入源不可达也应做（防护原语正确性不依赖调用方自律）。
- **同一防护原语的 N 处复制是"一个缺陷 ×N"**：发现一处 `startswith` 式包含判定，`grep startswith(str(` 全仓扫同错族一次收口；沉淀时也按"原语"沉淀而非按"端点"，否则下轮又会在新端点重犯。
- **端点测试 mock 掉防护层 = 防线零覆盖**：下载端点测缓存头/304 全用 `mocker.patch(get_task_image_file)`，真实边界从未被请求穿过。防护函数至少配一组**不经过 mock 的 service 层直测**（本例 `TaskService.__new__` 绕开 `__init__` 直测纯路径方法）。

D27 修复后按 `startswith(str(` / `extractall` / URL 前缀判定 三个变体族横扫四仓（web·algorithm·setting·media），结论：`startswith(str(` 形态 web 仓 5 处已在 D27 一次收口，其余三仓**零命中**；变体族逐点翻案理由如下（下轮勿重复审计）：

- **`zf.extractall(base_dir)`（algorithm `model_loader._load_dir_model` / `zapk_loader._unpack`）—— 翻案**：zip-slip 是否可达取决于成员名可否外部控制；此处 zip 由 `.enc` 解密得来，`.enc` 经 AES-GCM **tag 认证**（tag 不符即 `InvalidTag` 抛）+ v3 叠加 `sha256(plain)==model_hash` 强校验，明文 zip 由签发侧 `pack_zapk` 打包成员名固定 `models/…`。攻击者无法造「过双校验 + 成员名含 `../`」的 zip，解包 sink 输入源不可达。（若未来出现「解包非 GCM 认证的外部 zip」需重新评估。）

- **签名/审计中间件前缀清单 `path.startswith(MACHINE_PREFIXES/SENSITIVE_PREFIXES)`（setting `signature.py`/`audit_mw.py`）—— 翻案**：这些是 **fail-closed 方向**（前缀命中 = **多**要求签名/审计，不是绕过），前缀过匹配只会让某路由被更严对待，无越权语义；且 `MACHINE_PREFIXES` 是完整路由前缀（`/v1/licenses/renew` 等），注释明示「startswith 同时覆盖 /renew 与 /renew-request」是**设计意图**。

- **宽限期写封锁豁免 `path.startswith(ALWAYS_ALLOWED_PATHS)`（web `state.is_write_request`）—— 翻案**：fail-open 豁免（命中=不算写、放行），逐条核对前缀命中的路由（`/v1/system/license*` 全是自救通道 import/sync/renew-request，`/init`·`/activate` 未初始化态本要放行、activate 一次性消耗）——无「非自救写路由被误放行」，语义正确。

- **media 签名判定 `url.startswith(media_*_base_url)`（web `media_sign.sign_stream_url`）—— 翻案**：base 是完整 `scheme://host:port`（含端口），前缀判定只决定「是否给我方 media 地址附 sign」，误判方向是「第三方地址被多签名/我方地址漏签名（→prod 被验签拒）」，**无越权读取语义**；验签侧在 media（`media_sign.js` 定长比较 + prod 无 secret fail-closed）独立把守。

## 参考

- 源记录: `docs/known-pitfalls/backend/任务派发与算法联动.md` 「「文件在目录内」用 `str(path).startswith(str(root))` 判定：字符串前缀 ≠ 路径段包含，兄弟目录 `images_backup` 越界读/`rmtree` 递归删」
