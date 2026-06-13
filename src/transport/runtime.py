"""Process-wide selection of the active inference transport.

Inference call sites obtain the transport via :func:`get_inference_transport`
instead of importing the Socket.IO ``sio`` object directly. This keeps the
engine transport-agnostic: the default is Socket.IO (today's HF Space / VM
behaviour), and the ACI worker installs a Web PubSub transport — either by
setting ``INFERENCE_TRANSPORT=webpubsub`` (the default builder honours it) or
explicitly via :func:`set_inference_transport`.
"""

from __future__ import annotations

import asyncio
from typing import Optional

from src.transport.inference_transport import (
    InferenceTransport,
    build_inference_transport_from_env,
)

_transport: Optional[InferenceTransport] = None


async def _socketio_wait_for_client(job_id: str, timeout: float) -> Optional[str]:
    """Block until the browser connects with this ``job_id`` (Socket.IO).

    Mirrors the historical ``roadmap_engine.wait_for_socket`` so behaviour is
    preserved when the Socket.IO transport is active.
    """
    import src.socket_server as socket_server

    existing = socket_server.get_socket_for_job(job_id)
    if existing:
        return existing

    evt = socket_server.register_job_waiter(job_id)
    try:
        await asyncio.wait_for(evt.wait(), timeout=timeout)
        return socket_server.get_socket_for_job(job_id)
    except asyncio.TimeoutError:
        return None
    finally:
        socket_server.cleanup_job_waiter(job_id)


def _build_default() -> InferenceTransport:
    # Imported lazily so importing this module never forces the Socket.IO server
    # to spin up (the ACI worker runs without it).
    import src.socket_server as socket_server

    return build_inference_transport_from_env(
        sio=socket_server.sio,
        resolve_target=socket_server.get_socket_for_job,
        wait_for_client_fn=_socketio_wait_for_client,
    )


def get_inference_transport() -> InferenceTransport:
    global _transport
    if _transport is None:
        _transport = _build_default()
    return _transport


def set_inference_transport(transport: InferenceTransport) -> None:
    """Install an explicit transport (used by the ACI worker)."""
    global _transport
    _transport = transport


def reset_inference_transport() -> None:
    """Drop the cached transport (used in tests)."""
    global _transport
    _transport = None
