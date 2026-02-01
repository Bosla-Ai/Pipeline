import uvicorn
import socketio

from src.api import app as fastapi_app
from src.socket_server import sio

combined_app = socketio.ASGIApp(sio, other_asgi_app=fastapi_app)

print("✅ [SYSTEM] Bosla Pipeline Ready to Launch", flush=True)

if __name__ == "__main__":
    print("🔵 Pipeline Server running on http://localhost:7860")
    uvicorn.run("src.main:combined_app", host="0.0.0.0", port=7860, reload=True)
