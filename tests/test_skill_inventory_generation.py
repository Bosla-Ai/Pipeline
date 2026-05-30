import sys
import pytest
import subprocess
from pathlib import Path
from src.graph_inventory.generate import (
    generate_inventories_payloads,
    write_inventories,
    check_inventories,
    stable_json,
)


def test_stable_json_properties():
    payload = {"b": 2, "a": 1, "arabic": "عربي"}
    json_str = stable_json(payload)
    # Assert sort keys
    assert json_str.startswith('{\n  "a": 1,\n  "arabic": "عربي",\n  "b": 2\n}')
    # Assert UTF-8, no escaped arabic
    assert "عربي" in json_str
    # Assert exactly one trailing newline
    assert json_str.endswith("}\n")
    assert not json_str.endswith("}\n\n")


def test_validation_alias_target_missing(monkeypatch):
    monkeypatch.setattr(
        "src.graph_inventory.generate.load_aliases",
        lambda: {"alias_key": "nonexistent"},
    )
    monkeypatch.setattr("src.graph_inventory.generate.load_context_aliases", lambda: {})
    monkeypatch.setattr("src.graph_inventory.generate.load_domain_mappings", lambda: {})
    monkeypatch.setattr(
        "src.graph_inventory.generate.load_skill_graphs", lambda: ({}, {})
    )

    with pytest.raises(ValueError) as excinfo:
        generate_inventories_payloads()
    assert "Alias target 'nonexistent' for alias 'alias_key' does not exist" in str(
        excinfo.value
    )


def test_validation_context_alias_target_missing(monkeypatch):
    monkeypatch.setattr("src.graph_inventory.generate.load_aliases", lambda: {})
    monkeypatch.setattr(
        "src.graph_inventory.generate.load_context_aliases",
        lambda: {"alias": [{"target": "nonexistent"}]},
    )
    monkeypatch.setattr("src.graph_inventory.generate.load_domain_mappings", lambda: {})
    monkeypatch.setattr(
        "src.graph_inventory.generate.load_skill_graphs", lambda: ({}, {})
    )

    with pytest.raises(ValueError) as excinfo:
        generate_inventories_payloads()
    assert (
        "Context alias target 'nonexistent' for context alias 'alias' does not exist"
        in str(excinfo.value)
    )


def test_validation_context_alias_missing_target_key(monkeypatch):
    monkeypatch.setattr("src.graph_inventory.generate.load_aliases", lambda: {})
    monkeypatch.setattr(
        "src.graph_inventory.generate.load_context_aliases",
        lambda: {"alias": [{"default": True}]},
    )
    monkeypatch.setattr("src.graph_inventory.generate.load_domain_mappings", lambda: {})
    monkeypatch.setattr(
        "src.graph_inventory.generate.load_skill_graphs", lambda: ({}, {})
    )

    with pytest.raises(ValueError) as excinfo:
        generate_inventories_payloads()
    assert "Context alias 'alias' candidate is missing 'target'" in str(excinfo.value)


def test_validation_domain_mapping_key_missing(monkeypatch):
    monkeypatch.setattr("src.graph_inventory.generate.load_aliases", lambda: {})
    monkeypatch.setattr("src.graph_inventory.generate.load_context_aliases", lambda: {})
    monkeypatch.setattr(
        "src.graph_inventory.generate.load_domain_mappings",
        lambda: {"nonexistent": "Frontend Development"},
    )
    monkeypatch.setattr(
        "src.graph_inventory.generate.load_skill_graphs", lambda: ({}, {})
    )

    with pytest.raises(ValueError) as excinfo:
        generate_inventories_payloads()
    assert (
        "Domain mapping node ID 'nonexistent' does not exist in canonical tags"
        in str(excinfo.value)
    )


def test_validation_prereq_target_missing(monkeypatch):
    monkeypatch.setattr("src.graph_inventory.generate.load_aliases", lambda: {})
    monkeypatch.setattr("src.graph_inventory.generate.load_context_aliases", lambda: {})
    monkeypatch.setattr("src.graph_inventory.generate.load_domain_mappings", lambda: {})
    monkeypatch.setattr(
        "src.graph_inventory.generate.load_skill_graphs",
        lambda: ({"node_a": ["missing_node"]}, {"node_a": "file.yaml"}),
    )

    with pytest.raises(ValueError) as excinfo:
        generate_inventories_payloads()
    assert (
        "Node 'node_a' has missing/unknown prerequisite target 'missing_node'"
        in str(excinfo.value)
    )


def test_validation_difficulty_invalid_type(monkeypatch):
    monkeypatch.setattr("src.graph_inventory.generate.load_aliases", lambda: {})
    monkeypatch.setattr("src.graph_inventory.generate.load_context_aliases", lambda: {})
    monkeypatch.setattr("src.graph_inventory.generate.load_domain_mappings", lambda: {})
    monkeypatch.setattr(
        "src.graph_inventory.generate.load_skill_graphs",
        lambda: ({"node_a": {"difficulty": 123}}, {"node_a": "file.yaml"}),
    )

    with pytest.raises(ValueError) as excinfo:
        generate_inventories_payloads()
    assert "Node 'node_a' has invalid difficulty type" in str(excinfo.value)


def test_validation_estimated_hours_invalid_type(monkeypatch):
    monkeypatch.setattr("src.graph_inventory.generate.load_aliases", lambda: {})
    monkeypatch.setattr("src.graph_inventory.generate.load_context_aliases", lambda: {})
    monkeypatch.setattr("src.graph_inventory.generate.load_domain_mappings", lambda: {})
    monkeypatch.setattr(
        "src.graph_inventory.generate.load_skill_graphs",
        lambda: ({"node_a": {"estimated_hours": "ten"}}, {"node_a": "file.yaml"}),
    )

    with pytest.raises(ValueError) as excinfo:
        generate_inventories_payloads()
    assert "Node 'node_a' has invalid estimated_hours type" in str(excinfo.value)


def test_validation_estimated_hours_boolean(monkeypatch):
    monkeypatch.setattr("src.graph_inventory.generate.load_aliases", lambda: {})
    monkeypatch.setattr("src.graph_inventory.generate.load_context_aliases", lambda: {})
    monkeypatch.setattr("src.graph_inventory.generate.load_domain_mappings", lambda: {})
    monkeypatch.setattr(
        "src.graph_inventory.generate.load_skill_graphs",
        lambda: ({"node_a": {"estimated_hours": True}}, {"node_a": "file.yaml"}),
    )

    with pytest.raises(ValueError) as excinfo:
        generate_inventories_payloads()
    assert "Node 'node_a' has invalid estimated_hours type" in str(excinfo.value)


def test_validation_prereqs_not_list(monkeypatch):
    monkeypatch.setattr("src.graph_inventory.generate.load_aliases", lambda: {})
    monkeypatch.setattr("src.graph_inventory.generate.load_context_aliases", lambda: {})
    monkeypatch.setattr("src.graph_inventory.generate.load_domain_mappings", lambda: {})
    monkeypatch.setattr(
        "src.graph_inventory.generate.load_skill_graphs",
        lambda: ({"node_a": {"prerequisites": "not-a-list"}}, {"node_a": "file.yaml"}),
    )

    with pytest.raises(ValueError) as excinfo:
        generate_inventories_payloads()
    assert "Node 'node_a' prerequisites must be a list" in str(excinfo.value)


def test_validation_prereq_not_string(monkeypatch):
    monkeypatch.setattr("src.graph_inventory.generate.load_aliases", lambda: {})
    monkeypatch.setattr("src.graph_inventory.generate.load_context_aliases", lambda: {})
    monkeypatch.setattr("src.graph_inventory.generate.load_domain_mappings", lambda: {})
    monkeypatch.setattr(
        "src.graph_inventory.generate.load_skill_graphs",
        lambda: ({"node_a": [123]}, {"node_a": "file.yaml"}),
    )

    with pytest.raises(ValueError) as excinfo:
        generate_inventories_payloads()
    assert "Node 'node_a' prerequisite '123' is not a string" in str(excinfo.value)


def test_validation_duplicate_canonical_ids_across_files(monkeypatch):
    mock_paths = [Path("file1.yaml"), Path("file2.yaml")]
    monkeypatch.setattr("src.graph_inventory.generate.DATA_DIR", Path("/mock/data"))
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr(Path, "glob", lambda self, pattern: mock_paths)

    call_count = 0

    def mock_open(*args, **kwargs):
        nonlocal call_count
        call_count += 1

        class MockFile:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                pass

            def read(self):
                return ""

        return MockFile()

    monkeypatch.setattr("builtins.open", mock_open)

    yaml_results = [{"node_a": None}, {"node_a": None}]
    yaml_call = 0

    def mock_yaml_load(*args, **kwargs):
        nonlocal yaml_call
        val = yaml_results[yaml_call]
        yaml_call += 1
        return val

    monkeypatch.setattr("yaml.safe_load", mock_yaml_load)

    with pytest.raises(ValueError) as excinfo:
        from src.graph_inventory.generate import load_skill_graphs

        load_skill_graphs()
    assert "Duplicate canonical node ID found: 'node_a'" in str(excinfo.value)


def test_cli_check_real_success():
    in_sync, stale_files = check_inventories()
    assert in_sync, f"Expected active files to be in sync, but: {stale_files}"


def test_cli_script_check_success():
    res = subprocess.run(
        [sys.executable, "scripts/generate_skill_inventory.py", "--check"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "in sync" in res.stdout


def test_cli_check_fails_when_missing(tmp_path):
    in_sync, stale = check_inventories(str(tmp_path))
    assert not in_sync
    assert any("missing" in s for s in stale)


def test_cli_check_fails_when_stale(tmp_path):
    write_inventories(str(tmp_path))
    stale_file = tmp_path / "tag_contract.json"
    stale_file.write_text("invalid json content\n", encoding="utf-8")

    in_sync, stale = check_inventories(str(tmp_path))
    assert not in_sync
    assert any("tag_contract.json is stale" in s for s in stale)


def test_cli_write_to_temp_dir(tmp_path):
    write_inventories(str(tmp_path))
    inv_file = tmp_path / "skill_inventory.json"
    con_file = tmp_path / "tag_contract.json"
    assert inv_file.exists()
    assert con_file.exists()

    # Assert they are in sync now
    in_sync, stale = check_inventories(str(tmp_path))
    assert in_sync


def test_cli_normal_mode_output():
    res = subprocess.run(
        [sys.executable, "scripts/generate_skill_inventory.py"],
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0
    assert "Generated data/generated/skill_inventory.json" in res.stdout
    assert "Generated data/generated/tag_contract.json" in res.stdout

    # Fetch expected values dynamically from generate_inventories_payloads()
    inv, _ = generate_inventories_payloads()
    assert f"Nodes: {inv['nodeCount']}" in res.stdout
    assert f"Aliases: {inv['aliasCount']}" in res.stdout
    assert f"Context aliases: {inv['contextAliasCount']}" in res.stdout
    assert f"Domain mappings: {inv['domainMappingCount']}" in res.stdout
