import json
import pathlib
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


def test_repo_root_finds_taxonomy_file():
    assert (repo_root() / "taxonomy.yaml").exists()


def test_committed_schema_matches_derivation():
    committed = json.loads(
        (repo_root() / "schema" / "frontmatter.schema.json").read_text(encoding="utf-8"))
    derived = derive_schema(load_taxonomy())
    assert committed == derived
    assert "dedup_key" not in committed["properties"]
