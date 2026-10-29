from __future__ import annotations
import datetime as _dt
import pathlib
import re
from dataclasses import dataclass
import yaml

_FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def _normalize_dates(fm: dict) -> dict:
    # YAML 会把未加引号的 2026-10-12 解析成 datetime.date; schema 要求 str, 统一归一为 ISO 字符串
    for k, v in fm.items():
        if isinstance(v, _dt.datetime):
            fm[k] = v.date().isoformat()
        elif isinstance(v, _dt.date):
            fm[k] = v.isoformat()
    return fm


# 列表语义字段(front-matter): 消费链大量使用 `in` 成员判断与 join/Counter 遍历。
# 手改 YAML 写成 `domain: frontend`(标量)或 `tags:`(空→None)时, `"front" in
# "frontend"` 是**子串**真——filter 假通过、related 截断 id 假命中、Counter 把
# 字符串拆成字母计数(第三十五轮走查 §53 实测)。与 §52 同理: front-matter 也是
# 不可信输入, 在 parse 单一入口归一, 全体消费方终身受益; 退化情况记入
# Entry.list_degraded 供 lint 点名(schema 校验看不到归一后的值)。
_LIST_FIELDS = ("domain", "tags", "related")


def _normalize_lists(fm: dict) -> list[str]:
    """就地归一列表字段, 返回退化描述(空=全部正常)。"""
    degraded: list[str] = []
    for k in _LIST_FIELDS:
        if k not in fm:
            continue
        v = fm[k]
        if isinstance(v, list):
            cleaned = [x for x in v if isinstance(x, str) and x]
            if len(cleaned) != len(v):
                degraded.append(f"{k}: 列表含非字符串元素, 已剔除")
            fm[k] = cleaned
        elif isinstance(v, str) and v:
            degraded.append(f"{k}: 应为列表, 标量 {v!r} 已按单元素列表处理")
            fm[k] = [v]
        elif v is None:
            del fm[k]  # `tags:` 空值 → 视作缺失(下游默认值生效)
            degraded.append(f"{k}: 空值(null), 已按缺失处理")
        else:
            del fm[k]
            degraded.append(f"{k}: 类型 {type(v).__name__} 非法, 已按缺失处理")
    return degraded


_CN_TERM = "。！？"
_ASCII_TERM = ".!?"
_FENCE_BLOCK_RE = re.compile(r"```.*?```", re.DOTALL)


def _first_sentence(text: str) -> str:
    """首个句末终止符处截断(保留终止符)。

    ASCII 终止符须**后接空白**且**前一字符非数字**——否则 `nginx 1.27.3 起支持`
    会从 `27.3` 那个点被剁开(版本号里的点后接空格是常态)。数字前置的点不当终止符
    会漏判 "value is 3. Next" 这类句界, 代价只是首句偏长, 对匹配面无害(仍有 limit 截断)。
    """
    for i, ch in enumerate(text):
        if ch in _CN_TERM:
            return text[: i + 1]
        if (ch in _ASCII_TERM and i + 1 < len(text) and text[i + 1].isspace()
                and i > 0 and not text[i - 1].isdigit()):
            return text[: i + 1]
    return text


def _nonempty_paragraphs(text: str) -> list[str]:
    """按空行分块, 块内剔除标题行并折叠空白, 返回非空块(与 summary 的取块规则同构)。"""
    out: list[str] = []
    for block in re.split(r"\n\s*\n", text):
        b = re.sub(r"\s+", " ", " ".join(
            ln for ln in block.splitlines() if not ln.strip().startswith("#"))).strip()
        if b:
            out.append(b)
    return out


@dataclass
class Entry:
    fm: dict
    body: str
    path: pathlib.Path
    yaml_error: str | None = None   # front-matter YAML 语法错误原文(第十三轮走查)
    list_degraded: tuple[str, ...] = ()  # 列表字段退化描述(§53, 供 lint 点名)

    def h1(self) -> str | None:
        for line in self.body.splitlines():
            s = line.strip()
            if s.startswith("# "):
                return s[2:].strip()
        return None

    def summary(self, limit: int = 120) -> str:
        # 按空行分块, 块内剔除标题行(标题可能与正文同块), 取第一个还有正文的块
        for block in re.split(r"\n\s*\n", self.body):
            lines = [ln for ln in block.splitlines() if not ln.strip().startswith("#")]
            b = re.sub(r"\s+", " ", " ".join(lines)).strip()
            if b:
                return b[:limit]
        return ""

    def sections_text(self, limit: int = 60) -> str:
        """各 H2 段首句拼接, 只供 index 匹配面(spec §4.2)。不进 INDEX.md、不进检索返回值。

        存在理由: summary 只取正文首块, 向既有条目追加新病灶面时检索面不增长,
        红线 #3 要求的"先 search 去重"因此自我失效。每段首句是有界的高密度匹配面。
        """
        from kb.dedup import h2_sections  # 运行期反向依赖本模块, 延迟导入避免环

        out = []
        for _header, content in h2_sections(self):
            # 围栏整块删除后再分段: 真首句常与紧随的代码块同段, 按段跳过会连主旨句一起丢
            paras = _nonempty_paragraphs(_FENCE_BLOCK_RE.sub("", content))
            if paras:
                out.append(_first_sentence(paras[0])[:limit])
        return " ".join(out)


def parse_entry(path: pathlib.Path) -> Entry:
    # utf-8-sig: 容忍 BOM(Windows 记事本/PowerShell Set-Content 存盘自带)。
    # BOM 留在文首会让 front-matter 正则不匹配 → 条目被 index 静默跳过、
    # search 不可见(第十三轮走查实测); 对无 BOM 文件行为不变。
    text = pathlib.Path(path).read_text(encoding="utf-8-sig")
    m = _FM_RE.match(text)
    if not m:
        return Entry(fm={}, body=text, path=pathlib.Path(path))
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError as exc:
        # 人手编辑的 front-matter 语法坏(缩进/tab/未闭合流)曾让 lint/index/stat 全库
        # Traceback、search 静默空库(坏文件挡住 index 重建后)。降级 fm={} 保调用方
        # 存活: 坏文件按"缺必填"被 lint 报出(精确消息见 lint_repo), 其余条目照常。
        return Entry(fm={}, body=text, path=pathlib.Path(path),
                     yaml_error=str(exc).replace("\n", " ")[:200])
    # YAML 根类型非 mapping(list/str/...)视为无 front-matter: fm={}, body=全文,
    # 由 lint 自然报必填缺失, 避免 _normalize_dates 对 list 抛 AttributeError
    if not isinstance(data, dict):
        return Entry(fm={}, body=text, path=pathlib.Path(path))
    fm = _normalize_dates(data)
    degraded = _normalize_lists(fm)
    body = m.group(2)
    return Entry(fm=fm, body=body, path=pathlib.Path(path),
                 list_degraded=tuple(degraded))


def dump_entry(entry: Entry) -> str:
    fm_text = yaml.safe_dump(entry.fm, allow_unicode=True, sort_keys=False).strip()
    body = entry.body if entry.body.startswith("\n") else "\n" + entry.body
    return f"---\n{fm_text}\n---\n{body}"


# kb 根生成物固定名, 不作为条目(唯一事实源; lint/index/gate/query 共用)
GENERATED_NAMES = {"INDEX.md", "index.jsonl", "index.draft.jsonl"}


def iter_entry_paths(repo_root) -> list[pathlib.Path]:
    """条目文件发现的**唯一**规则(第二十四轮走查 §42)。

    布局契约: 条目只住在 kb/<第一层目录=type>/<...>/<slug>.md; 点开头目录是
    挂载的外仓(有自己的 kb 根和 lint), 不进父仓视野。

    修复前 index/gate/query 用 `kb.rglob("*.md")` 全量扫, lint 却只走第一层目录
    ——两套定义漂移出"kb 根直下散文件进 index(可被检索消费)却逃过 lint 全部
    校验"的免检角落(坏 type/坏 status 照样进检索)。所有读写方一律走本函数,
    契约漂移在结构上不可能; 契约外的带 id 散文件由 lint 显式报错(见 stray)。
    """
    kb = pathlib.Path(repo_root) / "kb"
    if not kb.exists():
        return []
    out: list[pathlib.Path] = []
    for d in sorted(p for p in kb.iterdir() if p.is_dir() and not p.name.startswith(".")):
        for p in sorted(d.rglob("*.md")):
            if p.name in GENERATED_NAMES:
                continue
            out.append(p)
    return out


def stray_entry_paths(repo_root) -> list[pathlib.Path]:
    """布局契约外的"散落条目": kb 根直下的 *.md(非生成物)且带可解析 front-matter
    id, **或 front-matter YAML 语法坏**(§63: 判据只认"可解析 id"时, 语法坏的散
    文件——作者显然想写条目却同时滑了位置和语法——反而静默失踪, 恰是最该点名的一类;
    无 front-matter 的纯笔记 fm={} 且 yaml_error=None, 不受误伤)。它们被
    iter_entry_paths 排除在检索外, 但带 id 说明是手滑放错位置的条目
    (静默不可见比报错更糟), 由 lint 显式报出。只查 kb 根一层, 不下探点目录
    (外仓自管)。
    """
    kb = pathlib.Path(repo_root) / "kb"
    if not kb.exists():
        return []
    out: list[pathlib.Path] = []
    for p in sorted(kb.glob("*.md")):
        if p.name in GENERATED_NAMES:
            continue
        e = parse_entry(p)
        if e.fm.get("id") or e.yaml_error:
            out.append(p)
    return out
