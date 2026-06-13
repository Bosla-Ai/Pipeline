"""Unit tests for the on-demand ACI worker entry point.

Exercise the orchestration of ``run_worker`` (status transitions, sink writes,
exit codes, completion broadcast) with fakes — no engine, Web PubSub, or Cosmos
dependency. Also cover env parsing.
"""

import json

import pytest

from src.transport.runtime import reset_inference_transport
import src.worker_entry as we


@pytest.fixture(autouse=True)
def _reset_transport():
    yield
    reset_inference_transport()


class FakeTransport:
    def __init__(self):
        self.published = []
        self.closed = False

    async def publish(self, job_id, event, data):
        self.published.append((job_id, event, data))

    async def aclose(self):
        self.closed = True


class FakeSink:
    def __init__(self):
        self.calls = []

    async def set_running(self, job_id, tags, language):
        self.calls.append(("running", job_id, tags, language))

    async def complete(self, job_id, result):
        self.calls.append(("complete", job_id, result))

    async def fail(self, job_id, error):
        self.calls.append(("fail", job_id, error))

    async def aclose(self):
        self.calls.append(("aclose",))


class FakeEngine:
    def __init__(self, result=None, exc=None):
        self._result = result
        self._exc = exc
        self.generate_called_with = None

    async def generate(self, **kwargs):
        self.generate_called_with = kwargs
        if self._exc is not None:
            raise self._exc
        return self._result


async def _run(engine, transport, sink):
    return await we.run_worker(
        job_id="job-1",
        tags=["python"],
        language="en",
        prefer_paid=False,
        sources=None,
        tag_checkpoints=None,
        transport=transport,
        sink=sink,
        client_wait_timeout=1.0,
        engine_factory=lambda _t: engine,
    )


async def test_success_completes_and_returns_zero():
    transport, sink = FakeTransport(), FakeSink()
    engine = FakeEngine(result={"data": {"youtube": {}}, "ok": True})

    code = await _run(engine, transport, sink)

    assert code == 0
    kinds = [c[0] for c in sink.calls]
    assert kinds[0] == "running"  # status set before work
    assert ("complete", "job-1", {"data": {"youtube": {}}, "ok": True}) in sink.calls
    assert ("aclose",) in sink.calls
    assert transport.closed is True
    assert ("job-1", "job_done", {"status": "completed"}) in transport.published
    # the engine received the job parameters
    assert engine.generate_called_with["job_id"] == "job-1"
    assert engine.generate_called_with["tags"] == ["python"]


async def test_failure_marks_failed_and_returns_one():
    transport, sink = FakeTransport(), FakeSink()
    engine = FakeEngine(exc=RuntimeError("boom"))

    code = await _run(engine, transport, sink)

    assert code == 1
    assert ("running", "job-1", ["python"], "en") in sink.calls
    assert ("fail", "job-1", "boom") in sink.calls
    assert transport.closed is True
    assert any(
        ev == "job_done" and data.get("status") == "failed"
        for (_jid, ev, data) in transport.published
    )


async def test_failure_with_empty_exception_message_still_reports():
    transport, sink = FakeTransport(), FakeSink()

    class _Empty(Exception):
        def __str__(self):
            return ""

    engine = FakeEngine(exc=_Empty())
    code = await _run(engine, transport, sink)

    assert code == 1
    fail_calls = [c for c in sink.calls if c[0] == "fail"]
    assert fail_calls and fail_calls[0][2]  # non-empty error string recorded


# ── env parsing ───────────────────────────────────────────────────────────


def test_parse_sources_filters_unknown():
    from src.engine.models import CourseSource

    assert we._parse_sources(json.dumps(["youtube", "bogus"])) == [CourseSource.YOUTUBE]
    assert we._parse_sources(None) is None
    assert we._parse_sources("not json") is None


def test_parse_env_minimal(monkeypatch):
    monkeypatch.setenv("JOB_ID", "abc")
    monkeypatch.setenv("TAGS", json.dumps(["python", "fastapi"]))
    monkeypatch.delenv("SOURCES", raising=False)
    monkeypatch.setenv("PREFER_PAID", "true")
    env = we._parse_env()
    assert env["job_id"] == "abc"
    assert env["tags"] == ["python", "fastapi"]
    assert env["prefer_paid"] is True
    assert env["language"] == "en"


def test_parse_env_requires_job_id(monkeypatch):
    monkeypatch.delenv("JOB_ID", raising=False)
    monkeypatch.setenv("TAGS", json.dumps(["x"]))
    with pytest.raises(SystemExit):
        we._parse_env()
