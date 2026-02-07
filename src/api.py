import asyncio
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from enum import Enum
import src.socket_server as socket_server
from src.socket_server import sio

from src.fetchers.videos.youtube_fetcher import fetch as fetch_youtube
from src.fetchers.videos.coursera_fetcher import fetch_coursera
from src.fetchers.videos.udemy_fetcher import UdemyFetcher
from src.utils.cache import cache, generate_cache_key

app = FastAPI(title="Bosla Pipeline API")


class CourseSource(str, Enum):
    YOUTUBE = "youtube"
    UDEMY = "udemy"
    COURSERA = "coursera"


class RoadmapRequest(BaseModel):
    tags: List[str]
    prefer_paid: bool = False
    language: str = "en"
    sources: Optional[List[CourseSource]] = None


async def generate_roadmap_logic(
    tags: List[str],
    prefer_paid: bool,
    language: str,
    sources: Optional[List[CourseSource]] = None,
):
    print(f"🔵 [API] Logic Triggered. Waiting for active connection...")

    roadmap_result = {"youtube": {}, "coursera": {}, "udemy": {}}

    if not prefer_paid:
        active_sources = [CourseSource.YOUTUBE]
    else:
        if sources:
            active_sources = sources
        else:
            active_sources = [CourseSource.UDEMY]

    print(f"🔹 [API] Active Sources: {active_sources}")

    if CourseSource.YOUTUBE in active_sources:
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

        except Exception as e:
            print(f"❌ Error inside YouTube fetcher: {e}")

    paid_sources_requested = any(
        s in active_sources for s in [CourseSource.COURSERA, CourseSource.UDEMY]
    )

    if paid_sources_requested:
        print(f"🔹 [API] Request: Paid Content | Tags: {tags}")

        from src.utils.helpers import analyze_topic_scope

        current_sid = socket_server.active_socket_id
        if not current_sid:
            print(
                "⚠️ Warning: No React Client connected. AI Classification will be skipped."
            )

        broad_tags = []
        atomic_tags = []
        scope_cache = {}

        for tag in tags:
            scope = await analyze_topic_scope(sio, current_sid, tag)
            scope_cache[tag] = scope
            if scope == "Broad":
                broad_tags.append(tag)
            else:
                atomic_tags.append(tag)

        print(f"    📊 Scope Result: Broad={broad_tags}, Atomic={atomic_tags}")

        if broad_tags:
            async with DRIVER_LOCK:
                if GLOBAL_DRIVER:
                    try:
                        GLOBAL_DRIVER.current_url
                    except:
                        print("⚠️ [SYSTEM] Global Driver unresponsive")

                if CourseSource.COURSERA in active_sources:
                    try:
                        coursera_data = await fetch_coursera(
                            sio, broad_tags, language, driver=GLOBAL_DRIVER
                        )
                        roadmap_result["coursera"] = coursera_data
                    except Exception as e:
                        print(f"❌ [API] Coursera Error: {e}")

                await asyncio.sleep(1)

                if CourseSource.UDEMY in active_sources:
                    try:
                        await cache.connect()
                        udemy_cached = {}
                        udemy_tags_to_fetch = []

                        for tag in broad_tags:
                            cache_key = generate_cache_key("udemy", tag, language)
                            cached_result = await cache.get(cache_key)
                            if cached_result:
                                print(f"    ✅ [Cache Hit] Udemy: {tag}")
                                udemy_cached[tag] = cached_result
                            else:
                                udemy_tags_to_fetch.append(tag)

                        roadmap_result["udemy"] = udemy_cached

                        if not udemy_tags_to_fetch:
                            print("    ✅ [Udemy] All tags served from cache")
                        else:
                            udemy_fetcher = UdemyFetcher(
                                tags=udemy_tags_to_fetch,
                                limit=5,
                                headless=False,
                                driver=GLOBAL_DRIVER,
                            )
                            await asyncio.to_thread(udemy_fetcher.scrape)

                            udemy_results_map = udemy_fetcher.results

                            from src.utils.helpers import classify_via_frontend

                            for tag, candidates in udemy_results_map.items():
                                if not candidates:
                                    continue

                                current_sid = socket_server.active_socket_id
                                valid_udemy = await classify_via_frontend(
                                    sio, current_sid, tag, candidates
                                )

                                if not valid_udemy:
                                    print(
                                        f"    ℹ️ [AI] No selection for '{tag}', using fallback."
                                    )
                                    valid_udemy = candidates

                                if valid_udemy:
                                    valid_udemy.sort(
                                        key=lambda x: x.get("score", 0), reverse=True
                                    )
                                    winner = valid_udemy[0]
                                    roadmap_result["udemy"][tag] = winner
                                    # Cache the winner
                                    cache_key = generate_cache_key(
                                        "udemy", tag, language
                                    )
                                    await cache.set(cache_key, winner)
                                    print(
                                        f"    🏆 [AI] Udemy Winner: {winner['title'][:50]}..."
                                    )

                    except Exception as e:
                        print(f"❌ [API] Udemy Error: {e}")

        if atomic_tags and CourseSource.YOUTUBE in active_sources:
            try:
                print(f"    ⚛️ [Atomic] Fetching YouTube for: {atomic_tags}")
                youtube_data = await fetch_youtube(
                    sio,
                    current_sid,
                    atomic_tags,
                    language,
                    scope_cache=scope_cache,
                )
                roadmap_result["youtube"] = youtube_data
            except Exception as e:
                print(f"❌ [API] YouTube Error: {e}")

    return {"status": "success", "data": roadmap_result}


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
        language=request.language,
        sources=request.sources,
    )
