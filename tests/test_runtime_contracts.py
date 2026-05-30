import json
import pytest
from pathlib import Path
from src.graph_inventory.runtime_contracts import (
    load_tag_contract,
    load_skill_inventory,
    get_contract_metadata,
    clear_contract_cache,
    ContractUnavailableError,
)

@pytest.fixture(autouse=True)
def clean_cache():
    clear_contract_cache()
    yield
    clear_contract_cache()

def test_successful_load():
    # Verify that loading from the actual generated files works
    tag = load_tag_contract()
    inv = load_skill_inventory()
    meta = get_contract_metadata()
    
    assert tag["schemaVersion"] == 1
    assert "canonicalTags" in tag
    assert "aliases" in tag
    assert "contextAliases" in tag
    assert "domains" in tag
    
    assert inv["schemaVersion"] == 1
    assert "nodes" in inv
    
    assert meta["schemaVersion"] == 1
    assert meta["nodeCount"] == len(tag["canonicalTags"])
    assert meta["aliasCount"] == len(tag["aliases"])
    assert meta["contextAliasCount"] == len(tag["contextAliases"])
    assert meta["domainMappingCount"] == len(tag["domains"])

def test_cache_mutability_protection():
    # Modify returned dict and verify the next call returns original values
    tag1 = load_tag_contract()
    tag1["new_key"] = "hacked"
    
    tag2 = load_tag_contract()
    assert "new_key" not in tag2

def test_missing_files(monkeypatch, tmp_path):
    # Set GENERATED_DIR to a temporary directory with no files
    monkeypatch.setattr("src.graph_inventory.runtime_contracts.GENERATED_DIR", tmp_path)
    
    with pytest.raises(ContractUnavailableError) as excinfo:
        load_tag_contract()
    assert excinfo.value.public_message == "Generated tag contract is unavailable"
    assert "/home/" not in excinfo.value.public_message
    
    with pytest.raises(ContractUnavailableError) as excinfo:
        load_skill_inventory()
    assert excinfo.value.public_message == "Generated skill inventory is unavailable"
    assert "/home/" not in excinfo.value.public_message

def test_invalid_json(monkeypatch, tmp_path):
    monkeypatch.setattr("src.graph_inventory.runtime_contracts.GENERATED_DIR", tmp_path)
    # Write corrupt JSON
    (tmp_path / "tag_contract.json").write_text("not json content", encoding="utf-8")
    (tmp_path / "skill_inventory.json").write_text("not json content", encoding="utf-8")
    
    with pytest.raises(ContractUnavailableError) as excinfo:
        load_tag_contract()
    assert excinfo.value.public_message == "Generated tag contract is unavailable"
    assert "/home/" not in excinfo.value.public_message
    
    with pytest.raises(ContractUnavailableError) as excinfo:
        load_skill_inventory()
    assert excinfo.value.public_message == "Generated skill inventory is unavailable"
    assert "/home/" not in excinfo.value.public_message

def test_invalid_top_level_shape(monkeypatch, tmp_path):
    monkeypatch.setattr("src.graph_inventory.runtime_contracts.GENERATED_DIR", tmp_path)
    # Write array instead of dict
    (tmp_path / "tag_contract.json").write_text("[]", encoding="utf-8")
    (tmp_path / "skill_inventory.json").write_text("[]", encoding="utf-8")
    
    with pytest.raises(ContractUnavailableError) as excinfo:
        load_tag_contract()
    assert excinfo.value.public_message == "Generated tag contract is unavailable"
    
    with pytest.raises(ContractUnavailableError) as excinfo:
        load_skill_inventory()
    assert excinfo.value.public_message == "Generated skill inventory is unavailable"

def test_metadata_cross_check_mismatch(monkeypatch, tmp_path):
    monkeypatch.setattr("src.graph_inventory.runtime_contracts.GENERATED_DIR", tmp_path)
    
    # Write mismatched counts
    (tmp_path / "tag_contract.json").write_text(json.dumps({
        "canonicalTags": ["python"],
        "aliases": {},
        "contextAliases": {},
        "domains": {}
    }), encoding="utf-8")
    (tmp_path / "skill_inventory.json").write_text(json.dumps({
        "schemaVersion": 1,
        "nodeCount": 100,  # mismatch: 1 vs 100
        "aliasCount": 0,
        "contextAliasCount": 0,
        "domainMappingCount": 0
    }), encoding="utf-8")
    
    with pytest.raises(ContractUnavailableError) as excinfo:
        get_contract_metadata()
    assert excinfo.value.public_message == "Generated contract metadata is unavailable"
    assert "Count mismatch" in excinfo.value.internal_message
