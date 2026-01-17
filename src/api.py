import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import src.socket_server as socket_server
from src.socket_server import sio

from src.fetchers.videos.youtube_fetcher import fetch as fetch_youtube
from src.fetchers.videos.coursera_fetcher import fetch_coursera
from src.fetchers.videos.udemy_fetcher import UdemyFetcher

app = FastAPI(title="Bosla Pipeline API")


class RoadmapRequest(BaseModel):
    tags: List[str]
    prefer_paid: bool = False
    content_type: str = "playlist"
    language: str = "en"


async def generate_roadmap_logic(
    tags: List[str], prefer_paid: bool, content_type: str, language: str
):
    print(f"🔵 [API] Logic Triggered. Waiting for active connection...")

    # 1. Initialize result container
    roadmap_result = {"youtube": {}, "coursera": {}, "udemy": []}

    if not prefer_paid:
        # YouTube is fast, so we get the ID now
        current_sid = socket_server.active_socket_id
        if not current_sid:
            print(
                "⚠️ Warning: No React Client connected. AI Classification will be skipped."
            )

        try:
            print(f"⏳ Fetching Free Content (YouTube)... Lang: {language}")
            youtube_data = await fetch_youtube(sio, current_sid, tags, language)
            roadmap_result["youtube"] = youtube_data

        except Exception as e:
            print(f"❌ Error inside YouTube fetcher: {e}")

    else:
        print("⏳ Fetching Paid Content (Coursera API + Udemy Scraper)...")

        coursera_task = asyncio.create_task(fetch_coursera(sio, tags, language))

        try:
            udemy_fetcher = UdemyFetcher(query=" ".join(tags), limit=5, headless=True)
            await asyncio.to_thread(udemy_fetcher.scrape)
            # AI Classification for Udemy
            udemy_candidates = udemy_fetcher.results
            valid_udemy = []

            if udemy_candidates:
                from src.utils.helpers import classify_via_frontend

                print(
                    f"    🤖 AI Analyzing {len(udemy_candidates)} Udemy Candidates..."
                )
                # Refresh Socket ID just-in-time
                current_sid = socket_server.active_socket_id
                valid_udemy = await classify_via_frontend(
                    sio, current_sid, " ".join(tags), udemy_candidates
                )

                # If AI returns nothing (or headless), valid_udemy is empty or original list
                if not valid_udemy:
                    print(
                        "    ⚠️ AI rejected all Udemy items (or headless). Using raw candidates."
                    )
                    valid_udemy = udemy_candidates

            # Standardize Output: Map query tag to the Best Answer
            # Since Udemy search is for "tag1 tag2...", we assign the best result to the first tag
            if valid_udemy:
                # Sort by score
                valid_udemy.sort(key=lambda x: x.get("score", 0), reverse=True)
                winner = valid_udemy[0]
                primary_tag = tags[0]  # Assign to the main topic
                roadmap_result["udemy"] = {primary_tag: winner}
            else:
                roadmap_result["udemy"] = {}

        except Exception as e:
            print(f"❌ Error inside Udemy scraper: {e}")

        try:
            coursera_data = await coursera_task
            roadmap_result["coursera"] = coursera_data
        except Exception as e:
            print(f"❌ Error inside Coursera fetcher: {e}")

    return {"status": "success", "data": roadmap_result}


@app.post("/generate-roadmap")
async def generate_roadmap(request: RoadmapRequest):
    return await generate_roadmap_logic(
        tags=request.tags,
        prefer_paid=request.prefer_paid,
        content_type=request.content_type,
        language=request.language,
    )
