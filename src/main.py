from processors.classifier import classifier_result

result = classifier_result(
    input='C#',
    parameters=['.net','laravel','node']
)

# print(result['scores'])

# from fetchers.videos.youtube_fetcher import fetch
# import json

# results = fetch(['c#','linq','sql server','ef core','mvc.net','api.net'], 'beginner')
# # 2. Convert the list to a formatted JSON string
# formatted_json = json.dumps(results, indent=4) 
# # 3. Print the formatted string
# print(formatted_json)


import socketio
import uvicorn
from fetchers.videos.youtube_fetcher import fetch 

# 1. Create a standalone Socket.IO server (No FastAPI)
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
app = socketio.ASGIApp(sio)

# 2. Event: When React Connects
@sio.event
async def connect(sid, environ):
    print(f"\n✅ React Client Connected! ID: {sid}")
    print("   (Waiting for 'start_test' event to begin inference...)\n")

# 3. Event: Trigger Logic
# This allows you to start the test from the Frontend whenever you are ready
@sio.event
async def start_test(sid, data):
    print(f"🚀 Starting Test for User {sid}")
    print(f"   Tags: {data.get('tags')} | Level: {data.get('level')}")
    
    try:
        # CALL FETCH
        # We pass 'sio' and 'sid' so it can talk back to this specific React user
        results = await fetch(
            sio=sio, 
            socket_id=sid, 
            tags=data.get('tags', ['python']), 
            user_level=data.get('level', 'beginner'),
            max_results=5
        )
        
        print("🎉 Final Result stored in variable 'results'")
        # Send final JSON back to frontend just to see it there too
        await sio.emit('test_complete', results, to=sid)
        
    except Exception as e:
        print(f"❌ Error: {e}")

@sio.event
async def disconnect(sid):
    print(f"❌ Client Disconnected: {sid}")

if __name__ == "__main__":
    # Run this file directly
    print("🔵 Pipeline Server Running on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000)