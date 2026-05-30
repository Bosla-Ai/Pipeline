import sys
import argparse
from pathlib import Path

# Add project root to sys.path so src imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.graph_inventory.generate import write_inventories, check_inventories

def main():
    parser = argparse.ArgumentParser(description="Generate or check skill inventory and tag contract JSON contracts.")
    parser.add_argument("--check", action="store_true", help="Compare current generated files with source YAML files without writing them.")
    args = parser.parse_args()

    if args.check:
        in_sync, stale_files = check_inventories()
        if in_sync:
            print("Generated files are in sync with source YAMLs.")
            sys.exit(0)
        else:
            print("Generated files are out of sync or missing:", file=sys.stderr)
            for file in stale_files:
                print(f"  - {file}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            write_inventories()
            print("Successfully generated and wrote skill_inventory.json and tag_contract.json.")
            sys.exit(0)
        except Exception as e:
            print(f"Error generating inventory: {e}", file=sys.stderr)
            sys.exit(1)

if __name__ == "__main__":
    main()
