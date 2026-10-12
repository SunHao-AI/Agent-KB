import pathlib
import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]

REQUIRED_TYPES = {
    "decision", "spec", "plan", "pitfall", "rca",
    "howto", "reference", "retrospective",
}
REQUIRED_DOMAINS = {
    "backend", "frontend", "database", "devops", "security",
    "testing", "build", "algorithm", "process", "tooling",
}


def load_taxonomy():
    with open(ROOT / "taxonomy.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_taxonomy_has_all_types_and_domains():
    tax = load_taxonomy()
    assert set(tax["types"]) == REQUIRED_TYPES
    assert set(tax["domains"]) == REQUIRED_DOMAINS


def test_every_type_declares_template_and_sections():
    tax = load_taxonomy()
    for name, meta in tax["types"].items():
        assert meta["template"].endswith(".md"), name
        assert isinstance(meta["sections"], list) and meta["sections"], name


def test_enums_present():
    tax = load_taxonomy()
    assert tax["enums"]["status"][0] == "draft"
    assert "universal" in tax["enums"]["scope"]
    assert "speculative" in tax["enums"]["confidence"]
