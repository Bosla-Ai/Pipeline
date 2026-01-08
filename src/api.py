import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import src.socket_server as socket_server
from src.socket_server import sio
<<<<<<< HEAD

from src.fetchers.videos.youtube_fetcher import fetch as fetch_youtube
from src.fetchers.videos.coursera_fetcher import fetch_coursera
from src.fetchers.videos.udemy_fetcher import UdemyFetcher
=======
>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)

from src.fetchers.videos.youtube_fetcher import fetch as fetch_youtube
from src.fetchers.videos.coursera_fetcher import fetch_coursera
from src.fetchers.videos.udemy_fetcher import UdemyFetcher

app = FastAPI(title="Bosla Pipeline API")


class RoadmapRequest(BaseModel):
    tags: List[str]
    level: str
    prefer_paid: bool = False
    content_type: str = "video"
    language: str = "en"

<<<<<<< HEAD
<<<<<<< HEAD
=======
>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)

async def generate_roadmap_logic(
    tags: List[str], level: str, prefer_paid: bool, content_type: str, language: str
):
<<<<<<< HEAD
=======
async def generate_roadmap_logic(tags: List[str], level: str, prefer_paid: bool, content_type: str, language: str):
>>>>>>> d68d208 (coursera fetcher was Added)
=======
>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)
    current_sid = socket_server.active_socket_id
    print(f"🔵 [API] Logic Triggered. Current Socket ID: {current_sid}")

    # 1. Initialize result container
<<<<<<< HEAD
<<<<<<< HEAD
    roadmap_result = {"youtube": {}, "coursera": {}, "udemy": []}

    if not prefer_paid:
        if not current_sid:
            print(
                "⚠️ Warning: No React Client connected. AI Classification will be skipped."
            )

        try:
            print(
                f"⏳ Fetching Free Content (YouTube)... Level: {level}, Lang: {language}"
            )
            youtube_data = await fetch_youtube(sio, current_sid, tags, level, language)
            roadmap_result["youtube"] = youtube_data

=======
    roadmap_result = {
        "youtube": {},
        "coursera": {},
        "udemy": []
    }
=======
    roadmap_result = {"youtube": {}, "coursera": {}, "udemy": []}
>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)

    if not prefer_paid:
        if not current_sid:
            print(
                "⚠️ Warning: No React Client connected. AI Classification will be skipped."
            )

        try:
            print(
                f"⏳ Fetching Free Content (YouTube)... Level: {level}, Lang: {language}"
            )
            youtube_data = await fetch_youtube(sio, current_sid, tags, level, language)
            roadmap_result["youtube"] = youtube_data
<<<<<<< HEAD
            
>>>>>>> d68d208 (coursera fetcher was Added)
=======

>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)
        except Exception as e:
            print(f"❌ Error inside YouTube fetcher: {e}")

    else:
        print("⏳ Fetching Paid Content (Coursera API + Udemy Scraper)...")

        coursera_task = asyncio.create_task(
            fetch_coursera(sio, current_sid, tags, level, language)
        )

        try:
            udemy_fetcher = UdemyFetcher(query=" ".join(tags), limit=5, headless=True)
            udemy_fetcher.scrape()
            roadmap_result["udemy"] = udemy_fetcher.results
        except Exception as e:
            print(f"❌ Error inside Udemy scraper: {e}")

        try:
            coursera_data = await coursera_task
            roadmap_result["coursera"] = coursera_data
        except Exception as e:
            print(f"❌ Error inside Coursera fetcher: {e}")

<<<<<<< HEAD
<<<<<<< HEAD
    return {"status": "success", "data": roadmap_result}

=======
    return {
        "status": "success",
        "data": roadmap_result
    }
>>>>>>> d68d208 (coursera fetcher was Added)
=======
    return {"status": "success", "data": roadmap_result}

>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)

@app.post("/generate-roadmap")
async def generate_roadmap(request: RoadmapRequest):
    return await generate_roadmap_logic(
        tags=request.tags,
        level=request.level,
        prefer_paid=request.prefer_paid,
        content_type=request.content_type,
<<<<<<< HEAD
<<<<<<< HEAD
        language=request.language,
    )
=======
        language=request.language 
    )
>>>>>>> d68d208 (coursera fetcher was Added)
=======
        language=request.language,
    )
>>>>>>> 51d358c (Improved Youtube Result and Format project using black formatter)
