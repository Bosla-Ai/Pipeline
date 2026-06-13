"""Pluggable transport for edge (browser) inference RPC.

The roadmap pipeline does not run inference itself — it offloads
classification/relevance scoring to a model running in the *user's browser*.
Today that round-trip is a Socket.IO acknowledgement call::

    response = await sio.call(event="request_inference", data=..., to=sid, timeout=3.0)

On Azure Container Instances the raw Socket.IO server is unreachable from the
browser (containers get dynamic public IPs, and an ``https://`` page cannot open
an unencrypted ``ws://`` socket — mixed-content block). Azure Web PubSub solves
both: a single stable ``wss://`` endpoint with a real certificate, and
bidirectional group messaging. But Web PubSub has no built-in request/response,
so we layer correlation-id RPC on top of group messages.

Both inference call sites (``EdgeInferenceClient.classify`` and the
``helpers.InferenceBatcher``) only need two primitives:

* resolve / wait for the live browser bound to a job, and
* issue a request that returns the browser's reply.

This module abstracts exactly that behind a **job-centric** interface so the
engine no longer reaches for a transport object directly. ``SocketIOTransport``
preserves today's behaviour byte-for-byte; ``WebPubSubTransport`` is the ACI
path. Selection is by the ``INFERENCE_TRANSPORT`` env var.

Message contract over a Web PubSub group (``data`` of a ``sendToGroup`` frame):

    request:  {"type": "<event>",          "corrId": "<uuid>", "role": "worker",  "payload": {...}}
    reply:    {"type": "<event>_result",    "corrId": "<uuid>", "role": "browser", "payload": [...]}
    ready:    {"type": "client_ready",                          "role": "browser"}

``call`` returns the reply's ``payload`` (a list), matching what ``sio.call``
returned, so downstream validation in ``edge_client``/``helpers`` is unchanged.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from abc import ABC, abstractmethod
from typing import Any, Awaitable, Callable, Optional

from src.utils.event_log import event_log

# Azure Web PubSub JSON WebSocket subprotocol.
WEBPUBSUB_SUBPROTOCOL = "json.webpubsub.azure.v1"

# Roles tag the sender of a group message so a participant can ignore its own echo.
ROLE_WORKER = "worker"
ROLE_BROWSER = "browser"

READY_EVENT = "client_ready"


class InferenceTransport(ABC):
    """Job-centric request/response channel to the browser inference node."""

    name: str = "base"

    @abstractmethod
    async def call(
        self, *, job_id: str, event: str, data: dict, timeout: float
    ) -> Optional[Any]:
        """Send ``event`` for ``job_id`` and return the browser's reply payload.

        Returns ``None`` if no browser is attached, on timeout, or on transport
        error — callers already treat a falsy/non-list reply as "no inference".
        """

    @abstractmethod
    def target_for_job(self, job_id: str) -> Optional[str]:
        """Return an opaque truthy target if a browser is attached, else ``None``.

        Replaces ``socket_server.get_socket_for_job`` at the call sites: the
        engine only uses the result as an "is a client attached?" guard and as a
        passthrough identifier, so a group name (Web PubSub) works as well as a
        sid (Socket.IO).
        """

    async def wait_for_client(self, job_id: str, timeout: float) -> bool:
        """Block until the browser for ``job_id`` is ready, or ``timeout``.

        Returns ``True`` if a client is attached, ``False`` on timeout.
        """
        return True

    async def aclose(self) -> None:
        """Release any resources (sockets, background tasks)."""


class SocketIOTransport(InferenceTransport):
    """Behaviour-preserving wrapper around the existing Socket.IO server.

    ``resolve_target`` maps a ``job_id`` to a connected sid (today's
    ``socket_server.get_socket_for_job``). ``wait_for_client_fn`` is the
    existing waiter (``roadmap_engine.wait_for_socket``-style); when omitted,
    readiness is simply "is a sid mapped right now".
    """

    name = "socketio"

    def __init__(
        self,
        sio: Any,
        resolve_target: Callable[[str], Optional[str]],
        wait_for_client_fn: Optional[Callable[[str, float], Awaitable[Optional[str]]]] = None,
    ) -> None:
        self._sio = sio
        self._resolve_target = resolve_target
        self._wait_for_client_fn = wait_for_client_fn

    async def call(
        self, *, job_id: str, event: str, data: dict, timeout: float
    ) -> Optional[Any]:
        target = self._resolve_target(job_id)
        if not target:
            return None
        try:
            return await self._sio.call(
                event=event, data=data, to=target, timeout=timeout
            )
        except Exception:
            return None

    def target_for_job(self, job_id: str) -> Optional[str]:
        return self._resolve_target(job_id)

    async def wait_for_client(self, job_id: str, timeout: float) -> bool:
        if self._wait_for_client_fn is not None:
            sid = await self._wait_for_client_fn(job_id, timeout)
            return bool(sid)
        return bool(self._resolve_target(job_id))


class WebPubSubTransport(InferenceTransport):
    """Correlation-id RPC over Azure Web PubSub group messages.

    The worker connects once as a Web PubSub *client*, joins the job's group,
    and exchanges request/reply frames with the browser in that group. A single
    background reader dispatches incoming frames to per-correlation futures.

    ``connector`` is injectable for testing: an awaitable ``(url, subprotocol)``
    returning a websocket-like object that supports ``await send(str)``, async
    iteration yielding ``str`` frames, and ``await close()``.
    """

    name = "webpubsub"

    def __init__(
        self,
        *,
        client_access_url: Optional[str] = None,
        url_provider: Optional[Callable[[], Awaitable[str]]] = None,
        group_for_job: Callable[[str], str] = lambda job: f"job:{job}",
        role: str = ROLE_WORKER,
        connector: Optional[Callable[[str, str], Awaitable[Any]]] = None,
    ) -> None:
        if not client_access_url and not url_provider:
            raise ValueError(
                "WebPubSubTransport needs client_access_url or url_provider"
            )
        self._client_access_url = client_access_url
        self._url_provider = url_provider
        self._group_for_job = group_for_job
        self._role = role
        self._connector = connector or self._default_connect

        self._ws: Any = None
        self._reader: Optional[asyncio.Task] = None
        self._connect_lock = asyncio.Lock()
        self._ack_id = 0

        self._joined: set[str] = set()
        self._group_to_job: dict[str, str] = {}
        self._pending: dict[str, asyncio.Future] = {}
        self._ready_events: dict[str, asyncio.Event] = {}

    # ── connection ──────────────────────────────────────────────────────
    @staticmethod
    async def _default_connect(url: str, subprotocol: str) -> Any:
        import websockets

        return await websockets.connect(
            url, subprotocols=[subprotocol], open_timeout=10
        )

    async def _ensure_connected(self) -> None:
        if self._ws is not None:
            return
        async with self._connect_lock:
            if self._ws is not None:
                return
            url = self._client_access_url
            if url is None and self._url_provider is not None:
                url = await self._url_provider()
            self._ws = await self._connector(url, WEBPUBSUB_SUBPROTOCOL)
            self._reader = asyncio.create_task(self._read_loop())

    async def _send_frame(self, frame: dict) -> None:
        await self._ensure_connected()
        await self._ws.send(json.dumps(frame))

    async def _ensure_joined(self, group: str, job_id: str) -> None:
        if group in self._joined:
            return
        self._group_to_job[group] = job_id
        self._ack_id += 1
        # Fire-and-forget join: frames on one socket are processed in order, so a
        # sendToGroup issued immediately after is delivered once the join lands.
        await self._send_frame(
            {"type": "joinGroup", "group": group, "ackId": self._ack_id}
        )
        self._joined.add(group)

    # ── reader ──────────────────────────────────────────────────────────
    async def _read_loop(self) -> None:
        try:
            async for raw in self._ws:
                try:
                    frame = json.loads(raw)
                except (ValueError, TypeError):
                    continue
                self._dispatch(frame)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pragma: no cover - connection drop
            event_log.log("warn", "transport", f"Web PubSub reader stopped: {exc}")

    def _dispatch(self, frame: dict) -> None:
        if frame.get("type") != "message" or frame.get("from") != "group":
            return
        data = frame.get("data")
        if not isinstance(data, dict):
            return
        # Ignore our own echo.
        if data.get("role") == self._role:
            return

        group = frame.get("group")
        job_id = self._group_to_job.get(group)

        if data.get("type") == READY_EVENT:
            if job_id is not None:
                self._ready_event(job_id).set()
            return

        corr = data.get("corrId")
        if corr and corr in self._pending:
            fut = self._pending.pop(corr)
            if not fut.done():
                fut.set_result(data.get("payload"))

    def _ready_event(self, job_id: str) -> asyncio.Event:
        evt = self._ready_events.get(job_id)
        if evt is None:
            evt = asyncio.Event()
            self._ready_events[job_id] = evt
        return evt

    # ── public API ──────────────────────────────────────────────────────
    async def call(
        self, *, job_id: str, event: str, data: dict, timeout: float
    ) -> Optional[Any]:
        group = self._group_for_job(job_id)
        try:
            await self._ensure_joined(group, job_id)
        except Exception:
            return None

        corr = uuid.uuid4().hex
        loop = asyncio.get_event_loop()
        fut: asyncio.Future = loop.create_future()
        self._pending[corr] = fut

        frame = {
            "type": "sendToGroup",
            "group": group,
            "noEcho": True,
            "dataType": "json",
            "data": {
                "type": event,
                "corrId": corr,
                "role": self._role,
                "payload": data,
            },
        }
        try:
            await self._send_frame(frame)
            return await asyncio.wait_for(fut, timeout=timeout)
        except (asyncio.TimeoutError, Exception):
            return None
        finally:
            self._pending.pop(corr, None)

    def target_for_job(self, job_id: str) -> Optional[str]:
        evt = self._ready_events.get(job_id)
        if evt is not None and evt.is_set():
            return self._group_for_job(job_id)
        return None

    async def publish(self, job_id: str, event: str, data: Any) -> None:
        """Fire-and-forget broadcast to the job group (e.g. live log events).

        No correlation id and no reply expected — used by the worker to stream
        logs/milestones to the frontend over the same group.
        """
        group = self._group_for_job(job_id)
        try:
            await self._ensure_joined(group, job_id)
            await self._send_frame(
                {
                    "type": "sendToGroup",
                    "group": group,
                    "noEcho": True,
                    "dataType": "json",
                    "data": {"type": event, "role": self._role, "payload": data},
                }
            )
        except Exception:
            # Logs are best-effort; never let streaming failures break the job.
            pass

    async def wait_for_client(self, job_id: str, timeout: float) -> bool:
        group = self._group_for_job(job_id)
        evt = self._ready_event(job_id)
        try:
            await self._ensure_joined(group, job_id)
        except Exception:
            return False
        if evt.is_set():
            return True
        try:
            await asyncio.wait_for(evt.wait(), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def aclose(self) -> None:
        if self._reader is not None:
            self._reader.cancel()
            try:
                await self._reader
            except (asyncio.CancelledError, Exception):
                pass
            self._reader = None
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self._pending.clear()


def build_inference_transport_from_env(
    *,
    sio: Any = None,
    resolve_target: Optional[Callable[[str], Optional[str]]] = None,
    wait_for_client_fn: Optional[
        Callable[[str, float], Awaitable[Optional[str]]]
    ] = None,
) -> InferenceTransport:
    """Select a transport from ``INFERENCE_TRANSPORT`` (``socketio``|``webpubsub``).

    Defaults to ``socketio`` so existing (HF Space / VM) deployments are
    unchanged. The ``webpubsub`` path reads ``WEBPUBSUB_CLIENT_ACCESS_URL``.
    """
    kind = os.getenv("INFERENCE_TRANSPORT", "socketio").strip().lower()

    if kind == "webpubsub":
        url = os.getenv("WEBPUBSUB_CLIENT_ACCESS_URL") or None
        return WebPubSubTransport(client_access_url=url)

    if sio is None or resolve_target is None:
        raise ValueError(
            "socketio transport requires sio and resolve_target"
        )
    return SocketIOTransport(sio, resolve_target, wait_for_client_fn)
