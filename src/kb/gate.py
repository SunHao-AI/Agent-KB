from __future__ import annotations
import datetime as dt
import json
import re
import sys
from pathlib import Path
from kb.dedup import fingerprint, fingerprint_source, fingerprint_text
from kb.entry import Entry, parse_entry, dump_entry, iter_entry_paths
from kb.new_entry import create_entry
from kb.taxonomy import load_taxonomy


class GateViolation(Exception):
    """门控拒绝: 试图做 Agent 不允许的写操作."""


class DuplicateCandidate(Exception):
    def __init__(self, entries: list[dict]):
        self.entries = entries
        super().__init__("duplicate candidates: "
                         + ", ".join(str(e.get("id")) for e in entries))


def _dedup_stopwords() -> frozenset[str]:
    return frozenset(load_taxonomy().get("dedup", {}).get("stopwords", []))


def _cjk_phrase(t: str) -> bool:
    """整段中文 token(≥3 字)在标题中是"词组"级信号, 单个命中即可判重;
    拉丁单词(vite/hmr 等)信息量低, 需多个同时命中."""
    return len(t) >= 3 and any("\u4e00" <= c <= "\u9fff" for c in t)


def _title_tokens(title: str) -> list[str]:
    """判重用标题 token(最多 3 个): 先剔泛词再截断, 防前 3 个全是泛词时无信号."""
    stops = _dedup_stopwords()
    toks = [t for t in re.split(r"[^0-9a-z\u4e00-\u9fff]+", title.lower())
            if len(t) >= 2 and t not in stops]
    return toks[:3]


def _index_records(repo: Path, name: str = "index.jsonl") -> list[dict]:
    jl = repo / "kb" / name
    if not jl.exists():
        return []
    return [json.loads(x) for x in jl.read_text(encoding="utf-8").splitlines() if x.strip()]


def _draft_records(repo: Path) -> list[dict]:
    """现算 draft 查重候选: draft 只进 index.draft.jsonl(不进检索/live 池), 且刚
    `kb new` 出的 draft 连 draft 索引都未重建 → 查重必须直接扫源文件现算指纹。
    draft 池小(低频、单会话≤3条), 现算成本可忽略, 换来无"索引未重建"时序窗口。"""
    out = []
    for p in iter_entry_paths(repo):   # 发现规则唯一事实源(§42)
        e = parse_entry(p)
        if e.fm.get("status") != "draft" or not e.fm.get("id"):
            continue
        out.append({"id": e.fm["id"], "title": e.fm.get("title", ""),
                    "dedup_key": fingerprint(e)})
    return out


def _tmp_entry(body: str) -> Entry:
    return Entry(fm={}, body=body, path=Path("<pending>"))


def _dup_hits(repos: list[Path], fp: str, title: str) -> list[dict]:
    """判重: 指纹相等, 或标题 token 命中既有标题且信号足够.

    信号规则(2026-10-21 误报治理, 原 any 单 token 即拒):
    - 泛词(windows/docker/append 等, 见 taxonomy dedup.stopwords)不计;
    - ≥3 字中文词组在标题中信息量高(中文不分词, 整段即一个 token),
      单个命中即判;
    - 拉丁/短词(vite/hmr)信息量低, 需 ≥2 个同时命中。
    指纹兜底不受本规则影响。
    """
    hits: list[dict] = []
    seen: set[str] = set()
    specific = _title_tokens(title)
    phrases = [t for t in specific if _cjk_phrase(t)]
    weak = [t for t in specific if not _cjk_phrase(t)]
    for rp in repos:
        # live 池(index.jsonl, 人工/定时维护恒有效) + draft 池(源文件现算指纹,
        # 覆盖"刚 kb new 未重建索引"的时序): 只比 live 会让两个 Agent 沉淀同一条
        # 知识双双通过, 重复 draft 又因不进检索索引而无法事后发现(第十六轮走查)。
        for r in _index_records(rp) + _draft_records(rp):
            rid = r.get("id")
            if rid in seen:
                continue
            hit = bool(fp) and r.get("dedup_key") == fp
            if not hit:
                hay = (r.get("title") or "").lower()
                hit = (any(t in hay for t in phrases)
                       or sum(1 for t in weak if t in hay) >= 2)
            if hit:
                hits.append({**r, "layer": rp.name})
                seen.add(rid)
    return hits


def _check_severity(severity: str | None) -> None:
    """severity 枚举守门(第三十八轮走查): CLI 面有 argparse choices 挡, MCP 面经
    gate 直写**没有**任何枚举校验——`severity='blocker'` 一路落盘进 draft 索引,
    lint 事后才报 schema 违规, 而索引已污染。写入口与 CLI 面等防, 枚举唯一事实源
    仍是 taxonomy.yaml。"""
    if severity is not None and severity not in load_taxonomy()["enums"]["severity"]:
        raise GateViolation(
            f"unknown severity: {severity} "
            f"(valid: {', '.join(load_taxonomy()['enums']['severity'])})")


def create_draft(repo, *, type: str, domain: str, title: str, body: str | None = None,
                 tags: list[str] | None = None, severity: str | None = None,
                 agent_kbs: tuple = (), today: dt.date | None = None) -> Entry:
    """Agent 唯一写入口: 强制 draft/speculative/project + 查重拒建."""
    _check_severity(severity)
    today = today or dt.date.today()
    repos = [Path(repo)] + [Path(p) for p in agent_kbs]
    fp = ""
    if body:
        # fingerprint_text 内含短源门槛(规范化后 <16 返回 ""), 单次提取+哈希
        fp = fingerprint_text(fingerprint_source(_tmp_entry(body)))
    hits = _dup_hits(repos, fp, title)
    if hits:
        raise DuplicateCandidate(hits)
    e = create_entry(Path(repo), type=type, domain=domain, scope="project",
                     title=title, generated=True, today=today)
    if body or tags or severity:
        cur = parse_entry(e.path)
        if body:
            cur.body = f"\n# {title}\n\n{body.strip()}\n"
        if tags:
            cur.fm["tags"] = list(tags)
        if severity:
            cur.fm["severity"] = severity
        e.path.write_text(dump_entry(cur), encoding="utf-8")
        e = parse_entry(e.path)
    _reindex(repo)  # §44: 新建 draft 要进 index.draft.jsonl——get_entry/kb_get/related
    return e        # 的底座 query._records 只读两个索引文件, 不重建则"create 返回
                    # id → 立即 kb_get 读全文"报 not found, stat 也漏计 backlog


_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"proposed", "accepted", "deprecated"},
    "proposed": {"draft", "accepted", "deprecated"},
    "accepted": {"deprecated", "superseded"},
    "deprecated": set(),
    "superseded": set(),
}

# accepted 起 N 天进入待复核(时效到期日 review_by, spec §属性表: "到期进入待复核
# 清单"; 周期取 1 年, 对齐 spec front-matter 示例 created 2026-10-12 → review_by
# 2027-10-12。知识会过期——§35 实测过"先命中后失效", accepted 不等于永久正确)。
# 第二十轮走查(§38): due_review/stat --due-review/AGENTS.md 工作流消费链完好,
# 但生产方为零——review_by 永不被写入, 待复核机制自上线起空转。
REVIEW_CYCLE_DAYS = 365


def _find(repo, id: str) -> Path:
    for p in iter_entry_paths(repo):   # 发现规则唯一事实源(§42)
        if parse_entry(p).fm.get("id") == id:
            return p
    raise FileNotFoundError(f"entry not found: {id}")


def _save(p: Path, fm: dict, body: str, today: dt.date) -> Entry:
    fm["updated"] = today.isoformat()
    p.write_text(dump_entry(Entry(fm=fm, body=body, path=p)), encoding="utf-8")
    return parse_entry(p)


def _reindex(repo) -> None:
    """写路径改完源文件后重建本仓索引(第二十五轮走查 §43)。

    search/去重的 live 池读 index.jsonl, 而 draft→accepted 流转让条目从"只在源文件
    (draft 池现算可见)"变为"应进 live 池"——不重建则检索与查重**双双隐身**: 红线1
    承诺的"agent 自审 accepted 无需等人工"闭环断裂, 且下一个任务感知不到它的存在,
    会把同一条知识重复沉淀。与 export_entry 搬移后重建双方索引(第十四轮)同一先例。
    repo_name 口径与 cli index 一致(resolve().name.lower())。"""
    from kb.index import build_indexes  # 局部导入: index 侧不反向依赖 gate
    build_indexes(Path(repo), repo_name=Path(repo).resolve().name.lower())


def update_draft(repo, id: str, *, title: str | None = None, body: str | None = None,
                 tags: list[str] | None = None, severity: str | None = None,
                 today: dt.date | None = None) -> Entry:
    """人工 CLI: 仅 draft 可编辑正文/元数据."""
    _check_severity(severity)
    p = _find(repo, id)
    e = parse_entry(p)
    if e.fm.get("status") != "draft":
        raise GateViolation(f"{id}: only draft entries are editable, current status={e.fm.get('status')}")
    fm = dict(e.fm)
    cur_body = e.body
    h1 = e.h1() or fm.get("title", "")
    if title:
        fm["title"] = title
        cur_body = cur_body.replace(f"# {h1}", f"# {title}", 1)
    if body:
        cur_body = f"\n# {fm.get('title', h1)}\n\n{body.strip()}\n"
    if tags is not None:
        fm["tags"] = list(tags)
    if severity:
        fm["severity"] = severity
    e = _save(p, fm, cur_body, today or dt.date.today())
    _reindex(repo)  # §44: title/body/tags 都是 draft 索引列(summary/dedup_key 派生
    return e        # 自它们), 滞留则 kb_get 返回旧文、去重指纹与面板展示全部失真


def review(repo, id: str, to: str, today: dt.date | None = None, *,
           by: str | None = None, confidence: str | None = None,
           evidence: str | None = None) -> Entry:
    """状态流转, 按 _TRANSITIONS; accepted 拒绝 speculative。

    by="agent" 为自审: accepted 时写 verified_by=agent + auto-reviewed 标签 +
    verification 留痕(供事后抽查回滚)。confidence 仅随 accepted 提升生效。
    人工流转带 evidence 时同样写 verification 留痕, 但不打自审标记。
    """
    p = _find(repo, id)
    e = parse_entry(p)
    fm = dict(e.fm)
    # confidence 枚举守门(第四十四轮走查 D-54, §56 severity 同判据): CLI 面有
    # argparse choices 挡, MCP kb_review 经 gate 直写没有——`confidence='verifed'`
    # 拼错时旧实现静默忽略(字段保持原值)却照常 accepted + 写 verification 留痕,
    # 调用方以为已提升 verified, 索引里实际还是 probable。
    if confidence is not None and confidence not in load_taxonomy()["enums"]["confidence"]:
        raise GateViolation(
            f"unknown confidence: {confidence} "
            f"(valid: {', '.join(load_taxonomy()['enums']['confidence'])})")
    if to == "accepted" and confidence in ("verified", "probable"):
        fm["confidence"] = confidence
    frm = e.fm.get("status", "")
    if to not in _TRANSITIONS.get(frm, set()):
        raise GateViolation(f"{id}: illegal transition {frm} -> {to}")
    if to == "accepted" and fm.get("confidence") == "speculative":
        raise GateViolation(f"{id}: confidence=speculative must be verified before accepted")
    fm["status"] = to
    if to == "accepted":
        # 时效到期日: accepted 不是终点, 到期进 due_review 清单(spec §时效性)。
        # 人工已显式设定 review_by 的不覆盖; 复核通过再次 accepted 时刷新周期。
        cur = fm.get("review_by")
        d = (today or dt.date.today())
        if not cur or str(cur) <= d.isoformat():
            fm["review_by"] = (d + dt.timedelta(days=REVIEW_CYCLE_DAYS)).isoformat()
    if to == "accepted" and by == "agent":
        fm["verified_by"] = "agent"
        tags = list(fm.get("tags") or [])
        if "auto-reviewed" not in tags:
            tags.append("auto-reviewed")
        fm["tags"] = tags
        d = (today or dt.date.today()).isoformat()
        fm["verification"] = {"evidence": (evidence or "").strip(), "reviewed_at": d}
    elif to == "accepted" and (evidence or "").strip():
        # 人工终审带证据: 同样写 verification 留痕, 但不打 auto-reviewed/verified_by
        d = (today or dt.date.today()).isoformat()
        fm["verification"] = {"evidence": evidence.strip(), "reviewed_at": d}
    e = _save(p, fm, e.body, today or dt.date.today())
    _reindex(repo)  # §43: status 是 live 池字段(draft→accepted 入池/降权依据), 不
    return e        # 重建则 accepted 条目对检索与查重双隐身, 红线1 闭环断裂


def _strip_promote_tags(fm: dict) -> list[str]:
    """终审落地时清掉建议期标签: needs-scope-review + promoted + promote-to:*(§39)。"""
    return [t for t in (fm.get("tags") or [])
            if t != "needs-scope-review" and not str(t).startswith("promote")]


def set_scope(repo, id: str, scope: str, today: dt.date | None = None) -> Entry:
    """人工 CLI: 设置 scope 并移除 needs-scope-review tag."""
    if scope not in load_taxonomy()["enums"]["scope"]:
        raise ValueError(f"unknown scope: {scope}")
    p = _find(repo, id)
    e = parse_entry(p)
    fm = dict(e.fm)
    fm["scope"] = scope
    fm["tags"] = _strip_promote_tags(fm)
    e = _save(p, fm, e.body, today or dt.date.today())
    _reindex(repo)  # §43: scope 是 live 池过滤字段, 索引滞留旧值则双层检索错层
    return e


def _project_name(path) -> str:
    """业务仓名: 取最近的 .git 祖先目录名(--repo 对 docs/kb 结构是仓内子目录,
    直接取尾段会得到 'docs' 这类无意义值), 无 .git 时退回目录名本身."""
    p = Path(path).resolve()
    for cand in (p, *p.parents):
        if (cand / ".git").exists():
            return cand.name
    return p.name


def export_entry(project_repo, agent_kb_repo, id: str, *, to_scope: str,
                 today: dt.date | None = None) -> Path:
    """人工 CLI: 将项目库条目搬到 Agent-KB 库(stack/universal), 回填 source.project."""
    if to_scope not in ("stack", "universal"):
        raise ValueError(f"export target scope must be stack/universal, got {to_scope}")
    target_kb = Path(agent_kb_repo) / "kb"
    if not target_kb.is_dir():
        # 目标仓必须已存在 kb/: 路径打错时旧实现 mkdir(parents=True) 静默建"假仓"
        # 并完成搬移+删源 → 条目从两仓索引双双消失(第十四轮走查)
        raise GateViolation(f"target repo has no kb/ dir, check --to-repo: {target_kb}")
    src = _find(project_repo, id)
    rel = src.relative_to(Path(project_repo) / "kb")
    dst = target_kb / rel
    if dst.exists():
        raise GateViolation(f"target already exists: {dst}")
    # §54: 路径检查挡不住"同 id 不同 slug"——目标仓已有早前从别处上提的同 id
    # 条目时, 搬入即让目标仓同 id 双条目(_find 只命中一个, 另一条 show/review
    # 断链), 且是**破坏性**搬移(src.unlink 已删源), 事后 lint 才发现=两仓都回不去。
    # 权威主键(id)的碰撞必须在写入点按主键查, 路径只是它的派生投影(D-35 同族,
    # 跨仓维度)。
    for p in iter_entry_paths(Path(agent_kb_repo)):
        if p != dst and parse_entry(p).fm.get("id") == id:
            raise GateViolation(
                f"target repo already has id {id} at {p.name}; "
                f"合并请先人工处理该条目, 勿重复上提")
    e = parse_entry(src)
    fm = dict(e.fm)
    if fm.get("status") != "accepted" or fm.get("confidence") == "speculative":
        # 未终审/未证结论搬入共享库是流程违规信号, 醒目提示但不拦(人工动作, 人有权带草稿)
        print(f"kb warning: {id} status={fm.get('status')} "
              f"confidence={fm.get('confidence')}, 未终审/未证条目已搬入共享库",
              file=sys.stderr)
    fm["scope"] = to_scope
    fm["tags"] = _strip_promote_tags(fm)
    fm["source"] = {**(fm.get("source") or {}),
                    "project": fm.get("source", {}).get("project") or _project_name(project_repo)}
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(dump_entry(Entry(fm=fm, body=e.body, path=dst)), encoding="utf-8")
    src.unlink()
    # 搬移后重建双方索引: 旧实现两仓 index 均滞留——源仓检索命中已删条目(断链),
    # 目标仓检索看不到新条目直到有人手动 kb index(第十四轮走查)
    from kb.index import build_indexes  # 局部导入: index 侧不反向依赖 gate
    build_indexes(Path(project_repo),
                  repo_name=Path(project_repo).resolve().name.lower())
    build_indexes(Path(agent_kb_repo),
                  repo_name=Path(agent_kb_repo).resolve().name.lower())
    return dst
