import socketio

sio = socketio.AsyncServer(
    async_mode="asgi",
    cors_allowed_origins=[
        "https://bosla.me",
        "https://front.bosla.almiraj.xyz",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "*",
    ],
)

active_socket_id = None


@sio.event
async def connect(sid, environ):
    global active_socket_id
    active_socket_id = sid
    print(f"✅ [SOCKET] React connected: {sid}")


@sio.event
async def disconnect(sid):
    global active_socket_id
    if active_socket_id == sid:
        active_socket_id = None
    print(f"❌ [SOCKET] React disconnected: {sid}")
