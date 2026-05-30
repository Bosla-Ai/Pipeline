import sys
import pytest
from httpx import AsyncClient, ASGITransport
from src.api import app
from src.graph_inventory.runtime_contracts import ContractUnavailableError

# Make sure event_log and redis connections are mocked or not causing issues
# During test execution under pytest, the tests/conftest.py handles basic bypasses.

@pytest.mark.asyncio
async def test_endpoints_successful_response(monkeypatch):
    # Enable dev bypass
    monkeypatch.setattr("src.api.PIPELINE_SHARED_SECRET", None)
    monkeypatch.setenv("ENVIRONMENT", "development")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # GET /contracts/tag-contract
        res = await ac.get("/contracts/tag-contract")
        assert res.status_code == 200
        data = res.json()
        assert "schemaVersion" in data
        assert "canonicalTags" in data
        assert "aliases" in data
        assert "contextAliases" in data
        assert "domains" in data

        # GET /contracts/skill-inventory
        res = await ac.get("/contracts/skill-inventory")
        assert res.status_code == 200
        data = res.json()
        assert "schemaVersion" in data
        assert "nodeCount" in data
        assert "nodes" in data

        # GET /contracts/metadata
        res = await ac.get("/contracts/metadata")
        assert res.status_code == 200
        data = res.json()
        assert "schemaVersion" in data
        assert "nodeCount" in data
        assert "aliasCount" in data
        assert "contextAliasCount" in data
        assert "domainMappingCount" in data


@pytest.mark.asyncio
async def test_endpoints_authentication(monkeypatch):
    # Set a test-secret
    monkeypatch.setattr("src.api.PIPELINE_SHARED_SECRET", "test-secret")
    
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        for path in ["/contracts/tag-contract", "/contracts/skill-inventory", "/contracts/metadata"]:
            # Calling without headers -> 401
            res = await ac.get(path)
            assert res.status_code == 401
            assert res.json()["detail"] == "Invalid pipeline secret"

            # Calling with wrong secret -> 401
            res = await ac.get(path, headers={"x-pipeline-secret": "wrong-secret"})
            assert res.status_code == 401
            assert res.json()["detail"] == "Invalid pipeline secret"

            # Calling with correct secret -> 200
            res = await ac.get(path, headers={"x-pipeline-secret": "test-secret"})
            assert res.status_code == 200


@pytest.mark.asyncio
async def test_endpoints_dev_bypass(monkeypatch):
    # Set no secret
    monkeypatch.setattr("src.api.PIPELINE_SHARED_SECRET", None)
    # Ensure not production environment to avoid 500 error
    monkeypatch.setenv("ENVIRONMENT", "development")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        for path in ["/contracts/tag-contract", "/contracts/skill-inventory", "/contracts/metadata"]:
            res = await ac.get(path)
            assert res.status_code == 200


@pytest.mark.asyncio
async def test_endpoints_error_sanitization(monkeypatch):
    def boom_tag():
        raise ContractUnavailableError(
            "Generated tag contract is unavailable",
            "/home/medo/Bosla/BoslaPipeline/data/generated/tag_contract.json is missing or corrupted"
        )
    def boom_inventory():
        raise ContractUnavailableError(
            "Generated skill inventory is unavailable",
            "/home/medo/Bosla/BoslaPipeline/data/generated/skill_inventory.json is missing or corrupted"
        )
    def boom_metadata():
        raise ContractUnavailableError(
            "Generated contract metadata is unavailable",
            "/home/medo/Bosla/BoslaPipeline/data/generated/skill_inventory.json counts mismatched"
        )

    monkeypatch.setattr("src.api.runtime_contracts.load_tag_contract", boom_tag)
    monkeypatch.setattr("src.api.runtime_contracts.load_skill_inventory", boom_inventory)
    monkeypatch.setattr("src.api.runtime_contracts.get_contract_metadata", boom_metadata)

    # Disable authentication by removing secret
    monkeypatch.setattr("src.api.PIPELINE_SHARED_SECRET", None)
    monkeypatch.setenv("ENVIRONMENT", "development")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        # tag contract error
        res = await ac.get("/contracts/tag-contract")
        assert res.status_code == 500
        assert res.json()["detail"] == "Generated tag contract is unavailable"
        assert "/home/" not in res.text
        assert "BoslaPipeline" not in res.text

        # skill inventory error
        res = await ac.get("/contracts/skill-inventory")
        assert res.status_code == 500
        assert res.json()["detail"] == "Generated skill inventory is unavailable"
        assert "/home/" not in res.text
        assert "BoslaPipeline" not in res.text

        # metadata error
        res = await ac.get("/contracts/metadata")
        assert res.status_code == 500
        assert res.json()["detail"] == "Generated contract metadata is unavailable"
        assert "/home/" not in res.text
        assert "BoslaPipeline" not in res.text
