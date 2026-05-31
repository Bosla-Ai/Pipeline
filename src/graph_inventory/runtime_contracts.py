import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, Optional

# Resolve paths relative to repository root
BASE_DIR = Path(__file__).resolve().parent.parent.parent
GENERATED_DIR = BASE_DIR / "data" / "generated"


class ContractUnavailableError(RuntimeError):
    """Exception raised when generated contracts are missing, malformed, or out of sync."""

    def __init__(self, public_message: str, internal_message: str | None = None):
        super().__init__(public_message)
        self.public_message = public_message
        self.internal_message = internal_message or public_message


# Internal cache variables
_tag_contract_cache: Optional[Dict[str, Any]] = None
_skill_inventory_cache: Optional[Dict[str, Any]] = None


def clear_contract_cache() -> None:
    """Clear in-memory contract caches (useful for tests)."""
    global _tag_contract_cache, _skill_inventory_cache
    _tag_contract_cache = None
    _skill_inventory_cache = None


def load_tag_contract() -> dict:
    """Load, cache, and return the tag contract payload.

    Raises:
        ContractUnavailableError if the file is missing or invalid JSON.
    """
    global _tag_contract_cache
    if _tag_contract_cache is not None:
        return deepcopy(_tag_contract_cache)

    path = GENERATED_DIR / "tag_contract.json"
    if not path.exists():
        raise ContractUnavailableError(
            "Generated tag contract is unavailable", f"File not found: {path.name}"
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Expected dictionary top-level shape")
        _tag_contract_cache = data
        return deepcopy(_tag_contract_cache)
    except (json.JSONDecodeError, ValueError) as e:
        raise ContractUnavailableError(
            "Generated tag contract is unavailable",
            f"Invalid JSON or shape in tag_contract.json: {e}",
        ) from e
    except Exception as e:
        raise ContractUnavailableError(
            "Generated tag contract is unavailable",
            f"Failed to read tag_contract.json: {e}",
        ) from e


def load_skill_inventory() -> dict:
    """Load, cache, and return the skill inventory payload.

    Raises:
        ContractUnavailableError if the file is missing or invalid JSON.
    """
    global _skill_inventory_cache
    if _skill_inventory_cache is not None:
        return deepcopy(_skill_inventory_cache)

    path = GENERATED_DIR / "skill_inventory.json"
    if not path.exists():
        raise ContractUnavailableError(
            "Generated skill inventory is unavailable", f"File not found: {path.name}"
        )
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("Expected dictionary top-level shape")
        _skill_inventory_cache = data
        return deepcopy(_skill_inventory_cache)
    except (json.JSONDecodeError, ValueError) as e:
        raise ContractUnavailableError(
            "Generated skill inventory is unavailable",
            f"Invalid JSON or shape in skill_inventory.json: {e}",
        ) from e
    except Exception as e:
        raise ContractUnavailableError(
            "Generated skill inventory is unavailable",
            f"Failed to read skill_inventory.json: {e}",
        ) from e


def get_contract_metadata() -> dict:
    """Calculate and return contract metadata, cross-checking counts between files.

    Raises:
        ContractUnavailableError if counts mismatch or files fail to load.
    """
    tag_contract = load_tag_contract()
    skill_inventory = load_skill_inventory()

    # Validate that counts match between both files
    tag_nodes = len(tag_contract.get("canonicalTags", []))
    tag_aliases = len(tag_contract.get("aliases", {}))
    tag_ctx_aliases = len(tag_contract.get("contextAliases", {}))
    tag_domains = len(tag_contract.get("domains", {}))

    inv_nodes = skill_inventory.get("nodeCount", 0)
    inv_aliases = skill_inventory.get("aliasCount", 0)
    inv_ctx_aliases = skill_inventory.get("contextAliasCount", 0)
    inv_domains = skill_inventory.get("domainMappingCount", 0)

    if (
        tag_nodes != inv_nodes
        or tag_aliases != inv_aliases
        or tag_ctx_aliases != inv_ctx_aliases
        or tag_domains != inv_domains
    ):
        raise ContractUnavailableError(
            "Generated contract metadata is unavailable",
            f"Count mismatch: tag_contract vs skill_inventory "
            f"(nodes: {tag_nodes} vs {inv_nodes}, "
            f"aliases: {tag_aliases} vs {inv_aliases}, "
            f"contextAliases: {tag_ctx_aliases} vs {inv_ctx_aliases}, "
            f"domains: {tag_domains} vs {inv_domains})",
        )

    return {
        "schemaVersion": skill_inventory.get("schemaVersion", 1),
        "nodeCount": inv_nodes,
        "aliasCount": inv_aliases,
        "contextAliasCount": inv_ctx_aliases,
        "domainMappingCount": inv_domains,
    }
