"""Unit tests for the pluggable inference transport.

These exercise the correlation-id RPC logic of ``WebPubSubTransport`` against a
fake websocket (no Azure required) and the behaviour-preserving
``SocketIOTransport`` wrapper.
"""

import asyncio
import json

import pytest

from src.transport.inference_transport import (
    SocketIOTransport,
    WebPubSubTransport,
    build_inference_transport_from_env,
)

_STOP = object()


class FakeWebSocket:
    """Minimal websocket double: records sent frames, replays fed frames."""

    def __init__(self):
        self.sent: list[dict] = []
        self.closed = False
        self._incoming: asyncio.Queue = asyncio.Queue()

    async def send(self, raw: str):
        self.sent.append(json.loads(raw))

    def feed(self, frame: dict):
        self._incoming.put_nowait(json.dumps(frame))

    def __aiter__(self):
        return self

    async def __anext__(self):
        raw = await self._incoming.get()
        if raw is _STOP:
            raise StopAsyncIteration
        return raw

    async def close(self):
        self.closed = True
        self._incoming.put_nowait(_STOP)


def _make_wps(role="worker"):
    ws = FakeWebSocket()

    async def connector(url, subprotocol):
        return ws

    transport = WebPubSubTransport(
        client_access_url="wss://example", role=role, connector=connector
    )
    return transport, ws


async def _wait_for(pred, timeout=2.0):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if pred():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met in time")


def _sent_of_type(ws, frame_type):
    return [f for f in ws.sent if f.get("type") == frame_type]


# ── SocketIOTransport ────────────────────────────────────────────────────


async def test_socketio_no_target_returns_none():
    transport = SocketIOTransport(sio=object(), resolve_target=lambda j: None)
    res = await transport.call(
        job_id="j", event="request_inference", data={}, timeout=1
    )
    assert res is None


async def test_socketio_delegates_to_sio_call():
    class FakeSio:
        def __init__(self):
            self.calls = []

        async def call(self, *, event, data, to, timeout):
            self.calls.append((event, data, to, timeout))
            return [{"candidate_key": "k", "label": "relevant", "confidence": 0.9}]

    sio = FakeSio()
    transport = SocketIOTransport(sio, resolve_target=lambda j: "sid-1")
    res = await transport.call(
        job_id="job", event="request_inference", data={"x": 1}, timeout=3
    )
    assert res == [{"candidate_key": "k", "label": "relevant", "confidence": 0.9}]
    assert sio.calls == [("request_inference", {"x": 1}, "sid-1", 3)]


async def test_socketio_swallows_exception():
    class BoomSio:
        async def call(self, **kwargs):
            raise RuntimeError("socket down")

    transport = SocketIOTransport(BoomSio(), resolve_target=lambda j: "sid")
    res = await transport.call(
        job_id="j", event="request_inference", data={}, timeout=1
    )
    assert res is None


async def test_socketio_wait_for_client_uses_resolver():
    transport = SocketIOTransport(object(), resolve_target=lambda j: "sid")
    assert await transport.wait_for_client("j", timeout=1) is True
    transport2 = SocketIOTransport(object(), resolve_target=lambda j: None)
    assert await transport2.wait_for_client("j", timeout=1) is False


# ── WebPubSubTransport ───────────────────────────────────────────────────


async def test_wps_request_reply_roundtrip():
    transport, ws = _make_wps()
    task = asyncio.create_task(
        transport.call(
            job_id="job1",
            event="request_inference",
            data={"candidates": [1, 2], "labels": ["a", "b"]},
            timeout=5,
        )
    )
    await _wait_for(lambda: _sent_of_type(ws, "sendToGroup"))

    # It must join the group before sending into it.
    assert _sent_of_type(ws, "joinGroup")
    join = _sent_of_type(ws, "joinGroup")[0]
    assert join["group"] == "job:job1"

    send = _sent_of_type(ws, "sendToGroup")[-1]
    assert send["group"] == "job:job1"
    assert send["data"]["role"] == "worker"
    assert send["data"]["payload"] == {"candidates": [1, 2], "labels": ["a", "b"]}
    corr = send["data"]["corrId"]

    ws.feed(
        {
            "type": "message",
            "from": "group",
            "group": "job:job1",
            "data": {
                "type": "request_inference_result",
                "corrId": corr,
                "role": "browser",
                "payload": [{"candidate_key": "k", "label": "relevant", "confidence": 1.0}],
            },
        }
    )
    res = await asyncio.wait_for(task, timeout=2)
    assert res == [{"candidate_key": "k", "label": "relevant", "confidence": 1.0}]
    await transport.aclose()


async def test_wps_timeout_returns_none():
    transport, ws = _make_wps()
    res = await transport.call(
        job_id="job1", event="request_inference", data={}, timeout=0.15
    )
    assert res is None
    await transport.aclose()


async def test_wps_ignores_own_echo():
    transport, ws = _make_wps()
    task = asyncio.create_task(
        transport.call(
            job_id="job1", event="request_inference", data={}, timeout=0.4
        )
    )
    await _wait_for(lambda: _sent_of_type(ws, "sendToGroup"))
    corr = _sent_of_type(ws, "sendToGroup")[-1]["data"]["corrId"]

    # Same correlation id but role=worker (our own echo) must not resolve it.
    ws.feed(
        {
            "type": "message",
            "from": "group",
            "group": "job:job1",
            "data": {
                "type": "request_inference",
                "corrId": corr,
                "role": "worker",
                "payload": {},
            },
        }
    )
    res = await task
    assert res is None
    await transport.aclose()


async def test_wps_ignores_unrelated_correlation():
    transport, ws = _make_wps()
    task = asyncio.create_task(
        transport.call(
            job_id="job1", event="request_inference", data={}, timeout=0.4
        )
    )
    await _wait_for(lambda: _sent_of_type(ws, "sendToGroup"))

    ws.feed(
        {
            "type": "message",
            "from": "group",
            "group": "job:job1",
            "data": {
                "type": "request_inference_result",
                "corrId": "some-other-id",
                "role": "browser",
                "payload": ["nope"],
            },
        }
    )
    res = await task
    assert res is None
    await transport.aclose()


async def test_wps_wait_for_client_ready():
    transport, ws = _make_wps()
    task = asyncio.create_task(transport.wait_for_client("job1", timeout=2))
    await _wait_for(lambda: _sent_of_type(ws, "joinGroup"))
    ws.feed(
        {
            "type": "message",
            "from": "group",
            "group": "job:job1",
            "data": {"type": "client_ready", "role": "browser"},
        }
    )
    assert await asyncio.wait_for(task, timeout=2) is True
    await transport.aclose()


async def test_wps_wait_for_client_timeout():
    transport, ws = _make_wps()
    assert await transport.wait_for_client("job1", timeout=0.15) is False
    await transport.aclose()


# ── factory ──────────────────────────────────────────────────────────────


def test_factory_socketio_requires_deps(monkeypatch):
    monkeypatch.delenv("INFERENCE_TRANSPORT", raising=False)
    with pytest.raises(ValueError):
        build_inference_transport_from_env()


def test_factory_socketio(monkeypatch):
    monkeypatch.setenv("INFERENCE_TRANSPORT", "socketio")
    transport = build_inference_transport_from_env(
        sio=object(), resolve_target=lambda j: None
    )
    assert isinstance(transport, SocketIOTransport)


def test_factory_webpubsub(monkeypatch):
    monkeypatch.setenv("INFERENCE_TRANSPORT", "webpubsub")
    monkeypatch.setenv("WEBPUBSUB_CLIENT_ACCESS_URL", "wss://example")
    transport = build_inference_transport_from_env()
    assert isinstance(transport, WebPubSubTransport)
