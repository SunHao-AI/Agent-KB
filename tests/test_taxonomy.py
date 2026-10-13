import json
import pathlib
import jsonschema
import yaml
from kb.taxonomy import load_taxonomy, derive_schema, repo_root

ROOT = pathlib.Path(__file__).resolve().parents[1]

REQUIRED_TYPES = {
    "decision", "spec", "plan", "pitfall", "rca",
    "howto", "reference", "retrospective",
}
REQUIRED_DOMAINS = {
    "backend", "frontend", "database", "devops", "security",
    "testing", "build", "algorithm", "process", "tooling",
}


def _load_repo_taxonomy():
    with open(ROOT / "taxonomy.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_taxonomy_has_all_types_and_domains():
    tax = _load_repo_taxonomy()
    assert set(tax["types"]) == REQUIRED_TYPES
    assert set(tax["domains"]) == REQUIRED_DOMAINS


def test_every_type_declares_template_and_sections():
    tax = _load_repo_taxonomy()
    for name, meta in tax["types"].items():
        assert meta["template"].endswith(".md"), name
        assert isinstance(meta["sections"], list) and meta["sections"], name


def test_enums_present():
    tax = _load_repo_taxonomy()
    assert tax["enums"]["status"][0] == "draft"
    assert "universal" in tax["enums"]["scope"]
    assert "speculative" in tax["enums"]["confidence"]


def test_derive_schema_marks_required_and_enums():
    schema = derive_schema(_load_repo_taxonomy())
    assert set(schema["required"]) >= {"id", "title", "type", "scope", "status", "confidence"}
    assert schema["properties"]["type"]["enum"] == sorted(REQUIRED_TYPES)
    assert schema["properties"]["severity"]["enum"] == ["low", "medium", "high", "critical"]


def _fm(**over) -> dict:
    fm = {
        "id": "kb-20261012-7f3a", "title": "t", "type": "pitfall",
        "domain": ["frontend"], "scope": "project", "status": "draft",
        "confidence": "speculative", "created": "2026-10-12", "updated": "2026-10-12",
    }
    fm.update(over)
    return fm


def test_derive_schema_conditional_required_pitfall_severity():
    # taxonomy types[*].requires 必须并入派生 schema: pitfall/rca 缺 severity → 校验失败;
    # 其他 type 缺 severity 不受影响(条件必填, 非全局必填)
    schema = derive_schema(_load_repo_taxonomy())
    v = jsonschema.Draft202012Validator(schema)
    assert v.is_valid(_fm(type="reference"))
    assert v.is_valid(_fm(type="pitfall", severity="high"))
    assert not v.is_valid(_fm(type="pitfall"))
    assert not v.is_valid(_fm(type="rca"))


def test_derive_schema_conditional_rule_needs_type_present():
    # if 子句同时 required type: type 字段本身缺失时不得被 if/then 误触发重复报错,
    # 但 root required 仍须报 type 缺失
    schema = derive_schema(_load_repo_taxonomy())
    v = jsonschema.Draft202012Validator(schema)
    fm = {k: v2 for k, v2 in _fm().items() if k != "type"}
    assert not v.is_valid(fm)  # type 缺失: root required 拦截
    msgs = [e.message for e in v.iter_errors(fm)]
    assert any("'type' is a required property" in m for m in msgs)


def test_repo_root_finds_taxonomy_file():
    assert (repo_root() / "taxonomy.yaml").exists()


def test_committed_schema_matches_derivation():
    committed = json.loads(
        (repo_root() / "schema" / "frontmatter.schema.json").read_text(encoding="utf-8"))
    derived = derive_schema(load_taxonomy())
    assert committed == derived
    assert "dedup_key" not in committed["properties"]
