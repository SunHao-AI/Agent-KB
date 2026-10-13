from __future__ import annotations
import functools
import pathlib
import yaml

_ID_PATTERN = r"^kb-\d{8}-[0-9a-f]{4}$"
_DATE_PATTERN = r"^\d{4}-\d{2}-\d{2}$"


def repo_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "taxonomy.yaml").exists():
            return parent
    return here.parents[2]


@functools.lru_cache(maxsize=1)
def _default_path() -> pathlib.Path:
    return repo_root() / "taxonomy.yaml"


def load_taxonomy(path: pathlib.Path | None = None) -> dict:
    p = pathlib.Path(path) if path else _default_path()
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f)


def derive_schema(tax: dict) -> dict:
    types = sorted(tax["types"])
    domains = sorted(tax["domains"])
    enums = tax["enums"]
    props = {
        "id": {"type": "string", "pattern": _ID_PATTERN},
        "title": {"type": "string", "minLength": 1},
        "type": {"type": "string", "enum": types},
        "domain": {
            "type": "array", "minItems": 1,
            "items": {"type": "string", "enum": domains},
        },
        "tags": {"type": "array", "items": {"type": "string"}},
        "scope": {"type": "string", "enum": enums["scope"]},
        "status": {"type": "string", "enum": enums["status"]},
        "severity": {"type": "string", "enum": enums["severity"]},
        "confidence": {"type": "string", "enum": enums["confidence"]},
        "created": {"type": "string", "pattern": _DATE_PATTERN},
        "updated": {"type": "string", "pattern": _DATE_PATTERN},
        "review_by": {"type": ["string", "null"], "pattern": _DATE_PATTERN},
        "source": {
            "type": "object",
            "properties": {"project": {"type": "string"}, "ref": {"type": "string"}},
        },
        "related": {"type": "array", "items": {"type": "string"}},
        "supersedes": {"type": ["string", "null"]},
        "superseded_by": {"type": ["string", "null"]},
    }
    # per-type 条件必填: taxonomy types[*].requires 非空的 type,
    # 用 draft 2020-12 allOf + if/then 生成"该 type 必须携带这些字段"规则。
    # if 子句同时 required type, 防 type 字段缺失时 const 误匹配导致误触发。
    conditionals = [
        {
            "if": {"properties": {"type": {"const": t}}, "required": ["type"]},
            "then": {"required": list(meta["requires"])},
        }
        for t, meta in sorted(tax["types"].items())
        if meta.get("requires")
    ]
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Agent-KB front-matter",
        "type": "object",
        "required": ["id", "title", "type", "domain", "scope",
                      "status", "confidence", "created", "updated"],
        "properties": props,
    }
    if conditionals:
        schema["allOf"] = conditionals
    return schema
