from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import src.socket_server as socket_server 
from src.socket_server import sio 

app = FastAPI(title="Bosla Pipeline API")

class RoadmapRequest(BaseModel):
    tags: List[str]
    level: str
    prefer_paid: bool = False
    content_type: str = "video"
    language: str = 'en'

async def generate_roadmap_logic(tags: List[str], level: str, prefer_paid: bool
                                 , content_type: str, langauge: str):
    current_sid = socket_server.active_socket_id
    
    print(f"🔵 [API] Logic Triggered. Current Socket ID: {current_sid}")

    # For paid (Udemy) content, socket connection is not required
    if not prefer_paid:
        if not current_sid:
            print("❌ Error: No Active Socket ID found.")
            return {"error": "No React Client Connected! Please open http://localhost:5173"}
    
    if not prefer_paid:
        try:
            from src.fetchers.videos.youtube_fetcher import fetch
            print("⏳ Calling Fetcher...")
            result = await fetch(
                tags=tags,
                user_level=level,
                sio=sio,
                socket_id=current_sid,
                language=langauge
            )
            return {"result": result}
            
        except Exception as e:
            print(f"❌ Error inside fetcher: {e}")
            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(e))
    else:
        from src.fetchers.videos.udemy_fetcher import UdemyFetcher
        fetcher = UdemyFetcher(query=" ".join(tags), limit=5, headless=True)
        fetcher.scrape()
        
        return {
            "status": "success",
            "query": " ".join(tags),
            "total_courses": len(fetcher.results),
            "courses": fetcher.results
        }

@app.post("/generate-roadmap")
async def generate_roadmap(request: RoadmapRequest):
    return await generate_roadmap_logic(
        tags=request.tags,
        level=request.level,
        prefer_paid=request.prefer_paid,
        content_type=request.content_type,
        langauge=request.language
    )