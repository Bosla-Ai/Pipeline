"""Unit tests for the progress emitter singleton."""

import pytest

from src.transport.runtime import set_inference_transport, reset_inference_transport
from src.utils.progress import progress


class RecordingTransport:
    """Captures publish() calls; mimics WebPubSubTransport.publish surface."""

    def __init__(self):
        self.published = []  # list of (job_id, event, data)

    async def publish(self, job_id, event, data):
        self.published.append((job_id, event, data))


class NoPublishTransport:
    """A transport without publish (like SocketIOTransport)."""


class BoomTransport:
    async def publish(self, job_id, event, data):
        raise RuntimeError("channel down")


@pytest.fixture(autouse=True)
def _clean_transport():
    reset_inference_transport()
    yield
    reset_inference_transport()


async def test_phase_publishes_typed_frame():
    t = RecordingTransport()
    set_inference_transport(t)
    await progress.phase("job1", "searching", label="Searching sources")
    assert t.published == [
        ("job1", "progress", {"kind": "phase", "phase": "searching", "label": "Searching sources"})
    ]


async def test_phase_without_label_omits_none_label():
    t = RecordingTransport()
    set_inference_transport(t)
    await progress.phase("job1", "done")
    assert t.published == [("job1", "progress", {"kind": "phase", "phase": "done", "label": None})]


async def test_item_found_includes_resource_and_candidates():
    t = RecordingTransport()
    set_inference_transport(t)
    await progress.item(
        "job1", "React Hooks", "found",
        resource={"title": "T", "url": "u", "source": "youtube", "score": 0.9},
    )
    await progress.item("job1", "React Hooks", "classifying", candidates=14)
    assert t.published[0] == (
        "job1", "progress",
        {"kind": "item", "tag": "React Hooks", "status": "found",
         "resource": {"title": "T", "url": "u", "source": "youtube", "score": 0.9}},
    )
    assert t.published[1] == (
        "job1", "progress",
        {"kind": "item", "tag": "React Hooks", "status": "classifying", "candidates": 14},
    )


async def test_item_minimal_omits_optional_keys():
    t = RecordingTransport()
    set_inference_transport(t)
    await progress.item("job1", "Go", "searching")
    assert t.published == [
        ("job1", "progress", {"kind": "item", "tag": "Go", "status": "searching"})
    ]


async def test_emit_is_noop_when_transport_lacks_publish():
    set_inference_transport(NoPublishTransport())
    # Must not raise.
    await progress.phase("job1", "analyzing")
    await progress.item("job1", "Go", "searching")


async def test_emit_swallows_publish_errors():
    set_inference_transport(BoomTransport())
    # Must not raise.
    await progress.phase("job1", "analyzing")
