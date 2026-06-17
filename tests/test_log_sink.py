"""Unit tests for the ACI worker's Cosmos log sink (buffering + flush + env build)."""

import pytest

from src.worker import log_sink as ls


class FakeContainer:
    def __init__(self):
        self.items = []

    async def upsert_item(self, doc):
        self.items.append(doc)


def test_build_log_sink_from_env_without_cosmos_is_noop(monkeypatch):
    monkeypatch.delenv("COSMOS_ENDPOINT", raising=False)
    monkeypatch.delenv("COSMOS_KEY", raising=False)
    sink = ls.build_log_sink_from_env("job-1")
    assert isinstance(sink, ls.NullLogSink)


def test_build_log_sink_from_env_with_cosmos(monkeypatch):
    monkeypatch.setenv("COSMOS_ENDPOINT", "https://example.documents.azure.com")
    monkeypatch.setenv("COSMOS_KEY", "secret")
    monkeypatch.setenv("COSMOS_LOGS_CONTAINER", "pipeline_logs")
    sink = ls.build_log_sink_from_env("job-1")
    assert isinstance(sink, ls.CosmosLogSink)
    assert sink._job_id == "job-1"
    assert sink._container_name == "pipeline_logs"


async def test_cosmos_log_sink_buffers_into_one_doc_and_flushes():
    sink = ls.CosmosLogSink(
        endpoint="e", key="k", database="agentdb", container="pipeline_logs", job_id="job-1"
    )
    # Pre-seed the container so _ensure() short-circuits (no azure-cosmos needed).
    fake = FakeContainer()
    sink._container = fake

    sink.record({"id": "1", "message": "a", "timestamp": "t1"})
    sink.record({"id": "2", "message": "b", "timestamp": "t2"})
    await sink.flush()

    assert len(fake.items) == 1  # one doc per job, not one per entry
    doc = fake.items[-1]
    assert doc["id"] == "job-1" and doc["jobId"] == "job-1"
    assert doc["count"] == 2 and len(doc["entries"]) == 2
    assert doc["ttl"] == 86400

    await sink.aclose()


async def test_cosmos_log_sink_caps_entries():
    sink = ls.CosmosLogSink(
        endpoint="e", key="k", database="agentdb", container="pipeline_logs", job_id="job-1"
    )
    fake = FakeContainer()
    sink._container = fake

    for i in range(ls.MAX_ENTRIES_PER_JOB + 50):
        sink.record({"id": str(i), "message": "x", "timestamp": "t"})
    await sink.flush()

    doc = fake.items[-1]
    assert doc["count"] == ls.MAX_ENTRIES_PER_JOB
    # Oldest entries dropped — newest retained.
    assert doc["entries"][-1]["id"] == str(ls.MAX_ENTRIES_PER_JOB + 49)

    await sink.aclose()


def test_null_log_sink_is_inert():
    sink = ls.NullLogSink()
    sink.record({"id": "1"})  # no error, no buffering
