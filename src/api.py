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
    roadmap_result = {"youtube": {}, "coursera": {}, "udemy": {}}

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
        print(f"🔹 [API] Request: Paid Content (Coursera + Udemy) | Tags: {tags}")

        async with DRIVER_LOCK:

            if GLOBAL_DRIVER:
                try:
                    GLOBAL_DRIVER.current_url
                except:
                    print("⚠️ [SYSTEM] Global Driver unresponsive")

            try:
                coursera_data = await fetch_coursera(
                    sio, tags, language, driver=GLOBAL_DRIVER
                )
                roadmap_result["coursera"] = coursera_data
            except Exception as e:
                print(f"❌ [API] Coursera Error: {e}")

            try:
                udemy_fetcher = UdemyFetcher(
                    tags=tags, limit=5, headless=False, driver=GLOBAL_DRIVER
                )
                await asyncio.to_thread(udemy_fetcher.scrape)

                # AI Classification for Udemy
                udemy_results_map = udemy_fetcher.results
                roadmap_result["udemy"] = {}

                from src.utils.helpers import classify_via_frontend

                for tag, candidates in udemy_results_map.items():
                    if not candidates:
                        continue

                    # Refresh Socket ID just-in-time
                    current_sid = socket_server.active_socket_id

                    valid_udemy = await classify_via_frontend(
                        sio, current_sid, tag, candidates
                    )

                    # If AI returns nothing (or headless), valid_udemy is empty or original list
                    if not valid_udemy:
                        print(
                            f"    ℹ️ [AI] No selection made for '{tag}', using fallback."
                        )
                        valid_udemy = candidates

                    if valid_udemy:
                        valid_udemy.sort(key=lambda x: x.get("score", 0), reverse=True)
                        winner = valid_udemy[0]
                        roadmap_result["udemy"][tag] = winner
                        print(f"    🏆 [AI] Udemy Winner: {winner['title'][:50]}...")

            except Exception as e:
                print(f"❌ [API] Udemy Error: {e}")

    return {"status": "success", "data": roadmap_result}


# Global Driver
GLOBAL_DRIVER = None
import asyncio

DRIVER_LOCK = asyncio.Lock()


@app.on_event("startup")
def startup_event():
    global GLOBAL_DRIVER
    try:
        import undetected_chromedriver as uc

        print("🔹 [SYSTEM] Initializing Global Chrome Driver...")
        options = uc.ChromeOptions()
        # options.add_argument("--headless=new") # Run headed in Xvfb
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")

        GLOBAL_DRIVER = uc.Chrome(options=options, version_main=144)
        print("✅ [SYSTEM] Global Driver Initialized & Ready")
    except Exception as e:
        print(f"❌ [SYSTEM] Driver Init Failed: {e}")


@app.on_event("shutdown")
def shutdown_event():
    global GLOBAL_DRIVER
    if GLOBAL_DRIVER:
        print("🛑 [SYSTEM] Shutting down Global Driver...")
        try:
            GLOBAL_DRIVER.quit()
        except:
            pass


@app.post("/generate-roadmap")
async def generate_roadmap(request: RoadmapRequest):
    return await generate_roadmap_logic(
        tags=request.tags,
        prefer_paid=request.prefer_paid,
        content_type=request.content_type,
        language=request.language,
    )
