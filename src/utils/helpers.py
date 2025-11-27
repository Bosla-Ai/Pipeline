import socketio

async def classify_via_frontend(sio: socketio.AsyncServer, socket_id: str, candidates: list, user_level: str):
    """
    Sends a list of candidates to the Frontend for AI classification.
    Waits for the Frontend to return ONLY the items matching 'user_level'.
    """
    
    if not candidates:
        return []

    print(f"📡 Sending {len(candidates)} items to Frontend ({socket_id}) for classification...")

    try:
        # This is the magic line. 
        # It sends the event and PAUSES here until the Frontend responds.
        filtered_results = await sio.call(
            event='request_inference',  # The event name the React hook listens for
            data={
                'candidates': candidates, 
                'user_level': user_level
            },
            to=socket_id,    # Target the specific user
            timeout=130       # Wait max 30 seconds
        )
        
        print(f"✅ Frontend returned {len(filtered_results)} valid items.")
        return filtered_results

    except TimeoutError:
        print("❌ Error: Frontend timed out (User might have closed the tab).")
        return []
    except Exception as e:
        print(f"❌ Error during classification: {e}")
        return []