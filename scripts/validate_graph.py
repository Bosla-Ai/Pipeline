import sys
import yaml
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

def load_aliases():
    path = DATA_DIR / "aliases.yaml"
    if not path.exists():
        return {}, [f"Aliases file {path} does not exist"]
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if data is None:
                return {}, []
            if not isinstance(data, dict):
                return {}, [f"Aliases file must contain a dictionary, got {type(data)}"]
            return data, []
    except Exception as e:
        return {}, [f"Failed to parse aliases.yaml: {e}"]

def load_skill_graphs():
    graphs_dir = DATA_DIR / "skill_graphs"
    if not graphs_dir.exists():
        return {}, {}, [f"Skill graphs directory {graphs_dir} does not exist"]
    
    combined_graph = {}
    node_sources = {}
    errors = []
    
    for path in graphs_dir.glob("*.yaml"):
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data is None:
                    continue
                if not isinstance(data, dict):
                    errors.append(f"File {path.name} must contain a dictionary, got {type(data)}")
                    continue
                for key, val in data.items():
                    if key in combined_graph:
                        errors.append(f"Duplicate canonical node key '{key}' found in both {node_sources[key]} and {path.name}")
                    else:
                        combined_graph[key] = val
                        node_sources[key] = path.name
        except Exception as e:
            errors.append(f"Failed to parse {path.name}: {e}")
            
    return combined_graph, node_sources, errors

def validate_graph(graph, aliases, node_sources):
    errors = []
    warnings = []
    
    for node, data in graph.items():
        if data is None:
            # Empty dictionary or None
            prereqs = []
        elif isinstance(data, list):
            prereqs = data
        elif isinstance(data, dict):
            prereqs = data.get("prerequisites", [])
        else:
            errors.append(f"Node '{node}' in {node_sources.get(node)} has invalid structure: {type(data)}")
            continue
            
        if not isinstance(prereqs, list):
            errors.append(f"Node '{node}' in {node_sources.get(node)} has non-list prerequisites: {type(prereqs)}")
            continue
            
        # Check prerequisites exist in graph
        for prereq in prereqs:
            # Normalize prerequisite using aliases
            clean_prereq = prereq.lower().replace("-", " ").strip()
            norm_prereq = aliases.get(clean_prereq, clean_prereq)
            if norm_prereq not in graph:
                errors.append(f"Node '{node}' in {node_sources.get(node)} has missing/unknown prerequisite '{prereq}' (normalized: '{norm_prereq}')")

    visited = {} # None: unvisited, 1: visiting, 2: visited
    
    def get_prereqs(n):
        val = graph.get(n)
        if val is None:
            return []
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            return val.get("prerequisites", []) or []
        return []

    def dfs(node_name):
        visited[node_name] = 1 # Visiting
        
        prereqs = get_prereqs(node_name)
        for prereq in prereqs:
            clean_p = prereq.lower().replace("-", " ").strip()
            norm_p = aliases.get(clean_p, clean_p)
            if norm_p not in graph:
                continue # Missing prereq check handled in step 1
                
            state = visited.get(norm_p, 0)
            if state == 1:
                return [node_name, norm_p]
            elif state == 0:
                cycle = dfs(norm_p)
                if cycle:
                    return [node_name] + cycle
                    
        visited[node_name] = 2 # Visited
        return None

    for node in graph:
        if visited.get(node, 0) == 0:
            cycle = dfs(node)
            if cycle:
                errors.append(f"Dependency cycle detected: {' -> '.join(cycle)}")
                break # Avoid spamming multiple cycles for the same path

    for alias_key, target in aliases.items():
        if target not in graph:
            errors.append(f"Alias '{alias_key}' points to target '{target}' which does not exist as a canonical node in the graph")

    # No alias key should exist as a canonical node in the graph
    for alias_key in aliases:
        if alias_key in graph:
            errors.append(f"Alias key '{alias_key}' is also defined as a canonical node in the graph. This is ambiguous.")

    # If 'tf' maps to 'tensorflow', warn about it because it is also used for 'terraform'
    if "tf" in aliases:
        target = aliases["tf"]
        warnings.append(
            f"Ambiguous alias warning: 'tf' maps to '{target}', but 'tf' is also commonly used for 'terraform'."
        )

    return errors, warnings

def main():
    aliases, alias_errors = load_aliases()
    graph, node_sources, graph_errors = load_skill_graphs()
    
    all_errors = alias_errors + graph_errors
    all_warnings = []
    
    if not all_errors:
        validation_errors, validation_warnings = validate_graph(graph, aliases, node_sources)
        all_errors.extend(validation_errors)
        all_warnings.extend(validation_warnings)
        
    print(f"Loaded {len(graph)} canonical nodes and {len(aliases)} aliases.")
    
    if all_warnings:
        print("\n--- WARNINGS ---")
        for warning in all_warnings:
            print(f"WARNING: {warning}")
            
    if all_errors:
        print("\n--- ERRORS ---")
        for error in all_errors:
            print(f"ERROR: {error}")
        print(f"\nValidation failed with {len(all_errors)} errors and {len(all_warnings)} warnings.")
        sys.exit(1)
        
    print("\nValidation passed successfully!")
    sys.exit(0)

if __name__ == "__main__":
    main()
