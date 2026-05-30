import os
import yaml
import json
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent.parent
DATA_DIR = BASE_DIR / "data"


def load_aliases() -> dict:
    """Load aliases mapping from aliases.yaml."""
    path = DATA_DIR / "aliases.yaml"
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def load_context_aliases() -> dict:
    """Load ambiguous aliases mapping from context_aliases.yaml."""
    path = DATA_DIR / "context_aliases.yaml"
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def load_domain_mappings() -> dict:
    """Load domain mappings from domain_mappings.yaml."""
    path = DATA_DIR / "domain_mappings.yaml"
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data or {}


def load_skill_graphs() -> tuple[dict, dict]:
    """Load and combine all skill graph nodes from YAML files in data/skill_graphs/."""
    graphs_dir = DATA_DIR / "skill_graphs"
    combined_graph = {}
    node_sources = {}
    
    for path in sorted(graphs_dir.glob("*.yaml")):
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if data is None:
                continue
            for key, val in data.items():
                if key in combined_graph:
                    raise ValueError(f"Duplicate canonical node ID found: '{key}' (in both {node_sources[key]} and {path.name})")
                combined_graph[key] = val
                node_sources[key] = path.name
                
    return combined_graph, node_sources


def generate_inventories_payloads() -> tuple[dict, dict]:
    """Generate in-memory structures for skill_inventory.json and tag_contract.json with strict validation."""
    aliases = load_aliases()
    context_aliases = load_context_aliases()
    domain_mappings = load_domain_mappings()
    combined_graph, node_sources = load_skill_graphs()
    
    # Validate alias targets exist in graph nodes
    for alias_key, target in aliases.items():
        if target not in combined_graph:
            raise ValueError(f"Alias target '{target}' for alias '{alias_key}' does not exist in canonical tags")
            
    # Validate context alias targets exist in graph nodes
    for alias_key, candidates in context_aliases.items():
        if not isinstance(candidates, list):
            raise ValueError(f"Context alias '{alias_key}' must map to a list")
        for cand in candidates:
            target = cand.get("target")
            if not target:
                raise ValueError(f"Context alias '{alias_key}' candidate is missing 'target'")
            if target not in combined_graph:
                raise ValueError(f"Context alias target '{target}' for context alias '{alias_key}' does not exist in canonical tags")
                
    # Validate domain mapping keys exist in graph nodes
    for node_id, domain in domain_mappings.items():
        if node_id not in combined_graph:
            raise ValueError(f"Domain mapping node ID '{node_id}' does not exist in canonical tags")
            
    # Validate prerequisites targets exist and metadata types are correct
    for node_id, val in combined_graph.items():
        if val is None:
            prereqs = []
        elif isinstance(val, list):
            prereqs = val
        elif isinstance(val, dict):
            if "prerequisites" in val:
                prereqs = val["prerequisites"]
            else:
                prereqs = []
            
            # Metadata type checking
            difficulty = val.get("difficulty")
            if difficulty is not None and not isinstance(difficulty, str):
                raise ValueError(f"Node '{node_id}' has invalid difficulty type: {type(difficulty)} (expected string)")
            
            est_hours = val.get("estimated_hours")
            if est_hours is not None:
                if isinstance(est_hours, bool) or not isinstance(est_hours, (int, float)):
                    raise ValueError(f"Node '{node_id}' has invalid estimated_hours type: {type(est_hours)} (expected int or float)")
        else:
            raise ValueError(f"Node '{node_id}' has invalid structure type: {type(val)}")
            
        if not isinstance(prereqs, list):
            raise ValueError(f"Node '{node_id}' prerequisites must be a list (got {type(prereqs)})")
            
        # Check prerequisite existence after simple alias normalization
        for prereq in prereqs:
            if not isinstance(prereq, str):
                raise ValueError(f"Node '{node_id}' prerequisite '{prereq}' is not a string")
            clean_prereq = prereq.lower().replace("-", " ").strip()
            norm_prereq = aliases.get(clean_prereq, clean_prereq)
            if norm_prereq not in combined_graph:
                raise ValueError(f"Node '{node_id}' has missing/unknown prerequisite target '{prereq}' (normalized: '{norm_prereq}')")
                
    # Build reverse-mapped simple aliases: target -> list[alias]
    aliases_map = {}
    for alias_key, target in aliases.items():
        if target not in aliases_map:
            aliases_map[target] = []
        aliases_map[target].append(alias_key)
        
    # Build reverse-mapped context aliases: target -> list[context_alias_key]
    context_aliases_map = {}
    for alias_key, candidates in context_aliases.items():
        for cand in candidates:
            target = cand.get("target")
            if target not in context_aliases_map:
                context_aliases_map[target] = []
            if alias_key not in context_aliases_map[target]:
                context_aliases_map[target].append(alias_key)
                
    # Build nodes list for skill_inventory.json (sorted by node ID)
    nodes = []
    for node_id in sorted(combined_graph.keys()):
        val = combined_graph[node_id]
        
        prereqs = []
        difficulty = None
        estimated_hours = None
        
        if isinstance(val, list):
            prereqs = val
        elif isinstance(val, dict):
            prereqs = val.get("prerequisites")
            if prereqs is None:
                prereqs = []
            difficulty = val.get("difficulty")
            estimated_hours = val.get("estimated_hours")
            
        nodes.append({
            "id": node_id,
            "sourceFile": node_sources[node_id],
            "prerequisites": sorted(list(prereqs)),
            "aliases": sorted(aliases_map.get(node_id, [])),
            "contextAliasKeys": sorted(context_aliases_map.get(node_id, [])),
            "domain": domain_mappings.get(node_id),  # Will be null if not found
            "difficulty": difficulty,
            "estimatedHours": estimated_hours
        })
        
    inventory_payload = {
        "schemaVersion": 1,
        "nodeCount": len(nodes),
        "aliasCount": len(aliases),
        "contextAliasCount": len(context_aliases),
        "domainMappingCount": len(domain_mappings),
        "nodes": nodes
    }
    
    # Build tag_contract.json
    # Sort each context list elements in contextAliases if present
    sorted_context_aliases = {}
    for alias_key, candidates in context_aliases.items():
        sorted_candidates = []
        for cand in candidates:
            new_cand = dict(cand)
            if "context" in new_cand and isinstance(new_cand["context"], list):
                new_cand["context"] = sorted(new_cand["context"])
            sorted_candidates.append(new_cand)
        sorted_context_aliases[alias_key] = sorted_candidates
        
    contract_payload = {
        "schemaVersion": 1,
        "canonicalTags": sorted(list(combined_graph.keys())),
        "aliases": aliases,
        "contextAliases": sorted_context_aliases,
        "domains": domain_mappings,
        "sourceFiles": node_sources
    }
    
    return inventory_payload, contract_payload


def stable_json(payload: dict) -> str:
    """Format payload to sorted, human-readable UTF-8 JSON with exactly one trailing newline."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def write_inventories(output_dir: str | None = None) -> dict:
    """Generate and write inventories to files on disk."""
    inventory_payload, contract_payload = generate_inventories_payloads()
    
    out_path = Path(output_dir) if output_dir else DATA_DIR / "generated"
    out_path.mkdir(parents=True, exist_ok=True)
    
    inv_file = out_path / "skill_inventory.json"
    con_file = out_path / "tag_contract.json"
    
    with open(inv_file, "w", encoding="utf-8") as f:
        f.write(stable_json(inventory_payload))
        
    with open(con_file, "w", encoding="utf-8") as f:
        f.write(stable_json(contract_payload))

    return inventory_payload


def check_inventories(output_dir: str | None = None) -> tuple[bool, list[str]]:
    """Check if existing files on disk exactly match current YAML sources."""
    inventory_payload, contract_payload = generate_inventories_payloads()
    
    out_path = Path(output_dir) if output_dir else DATA_DIR / "generated"
    inv_file = out_path / "skill_inventory.json"
    con_file = out_path / "tag_contract.json"
    
    stale_files = []
    
    # Check skill_inventory.json
    if not inv_file.exists():
        stale_files.append("skill_inventory.json is missing")
    else:
        with open(inv_file, "r", encoding="utf-8") as f:
            existing = f.read()
        expected = stable_json(inventory_payload)
        if existing != expected:
            stale_files.append("skill_inventory.json is stale/out of sync")
            
    # Check tag_contract.json
    if not con_file.exists():
        stale_files.append("tag_contract.json is missing")
    else:
        with open(con_file, "r", encoding="utf-8") as f:
            existing = f.read()
        expected = stable_json(contract_payload)
        if existing != expected:
            stale_files.append("tag_contract.json is stale/out of sync")
            
    return len(stale_files) == 0, stale_files
