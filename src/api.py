import asyncio
import uuid
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
from src.utils.learning_path import generate_learning_path

app = FastAPI(title="Bosla Pipeline API")


def preprocess_tags(tags: list[str]) -> list[str]:
    """
    Cleans and normalizes tags from the API before passing to fetchers.
    Handles rich descriptive tags like 'Automated Testing with Jest'.
    """
    cleaned = []
    seen = set()
    for tag in tags:
        t = tag.strip()
        if not t:
            continue
        t = " ".join(t.split())
        key = t.lower()
        if key not in seen:
            seen.add(key)
            cleaned.append(t)
    return cleaned


class CourseSource(str, Enum):
    YOUTUBE = "youtube"
    UDEMY = "udemy"
    COURSERA = "coursera"


class RoadmapRequest(BaseModel):
    tags: List[str]
    prefer_paid: bool = False
    language: str = "en"
    sources: Optional[List[CourseSource]] = None
    job_id: Optional[str] = None


@app.get("/stats")
async def stats():
    """Return connected sockets, active jobs, and connection details."""
    return socket_server.get_stats()


SOCKET_WAIT_TIMEOUT = 30


async def wait_for_socket(job_id: str) -> str | None:
    """Block until the frontend connects with this job_id, or timeout."""
    existing = socket_server.get_socket_for_job(job_id)
    if existing:
        return existing

    evt = socket_server.register_job_waiter(job_id)
    try:
        await asyncio.wait_for(evt.wait(), timeout=SOCKET_WAIT_TIMEOUT)
        return socket_server.get_socket_for_job(job_id)
    except asyncio.TimeoutError:
        print(
            f"⚠️ [JOB {job_id[:8]}] No frontend socket connected within {SOCKET_WAIT_TIMEOUT}s. Proceeding without AI."
        )
        return None
    finally:
        socket_server.cleanup_job_waiter(job_id)


async def generate_roadmap_logic(
    tags: List[str],
    prefer_paid: bool,
    language: str,
    sources: Optional[List[CourseSource]] = None,
    job_id: Optional[str] = None,
):
    if not job_id:
        job_id = uuid.uuid4().hex[:12]

    tags = preprocess_tags(tags)

    print(f"🔵 [JOB {job_id[:8]}] Roadmap requested. Tags: {tags}, Lang: {language}")
    print(f"   Waiting for frontend socket…")

    current_sid = await wait_for_socket(job_id)

    if current_sid:
        print(f"✅ [JOB {job_id[:8]}] Frontend socket ready (sid: {current_sid})")
    else:
        print(
            f"⚠️ [JOB {job_id[:8]}] No frontend socket. AI classification will be skipped."
        )

    roadmap_result = {"youtube": {}, "coursera": {}, "udemy": {}}

    if not prefer_paid:
        active_sources = [CourseSource.YOUTUBE]
    else:
        if sources:
            active_sources = sources
        else:
            active_sources = [CourseSource.UDEMY]

    print(f"🔹 [JOB {job_id[:8]}] Active Sources: {active_sources}")

    if CourseSource.YOUTUBE in active_sources:
        try:
            print(
                f"⏳ [JOB {job_id[:8]}] Fetching Free Content (YouTube)... Lang: {language}"
            )
            youtube_data = await fetch_youtube(sio, current_sid, tags, language)
            roadmap_result["youtube"] = youtube_data
        except Exception as e:
            print(f"❌ [JOB {job_id[:8]}] YouTube fetcher error: {e}")

    paid_sources_requested = any(
        s in active_sources for s in [CourseSource.COURSERA, CourseSource.UDEMY]
    )

    if paid_sources_requested:
        print(f"🔹 [JOB {job_id[:8]}] Fetching Paid Content | Tags: {tags}")

        from src.utils.helpers import analyze_topic_scope

        # Refresh sid in case the socket reconnected
        current_sid = socket_server.get_socket_for_job(job_id) or current_sid

        broad_tags = []
        atomic_tags = []
        scope_cache = {}

        async def analyze_tag(tag):
            scope = await analyze_topic_scope(sio, current_sid, tag)
            return tag, scope

        scope_results = await asyncio.gather(*(analyze_tag(t) for t in tags))
        for tag, scope in scope_results:
            scope_cache[tag] = scope
            if scope == "Broad":
                broad_tags.append(tag)
            else:
                atomic_tags.append(tag)

        print(
            f"    📊 [JOB {job_id[:8]}] Scope: Broad={broad_tags}, Atomic={atomic_tags}"
        )

        if broad_tags:
            fetch_tasks = []

            if CourseSource.COURSERA in active_sources:

                async def fetch_coursera_job():
                    try:
                        data = await fetch_coursera(
                            sio, current_sid, broad_tags, language, driver=GLOBAL_DRIVER
                        )
                        roadmap_result["coursera"] = data
                    except Exception as e:
                        print(f"❌ [JOB {job_id[:8]}] Coursera Error: {e}")

                fetch_tasks.append(fetch_coursera_job())

            if CourseSource.UDEMY in active_sources:

                async def fetch_udemy_job():
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
                            print(f"    ✅ [JOB {job_id[:8]}] Udemy: All tags cached")
                        else:
                            async with DRIVER_LOCK:
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

                                sid = (
                                    socket_server.get_socket_for_job(job_id)
                                    or current_sid
                                )
                                valid_udemy = await classify_via_frontend(
                                    sio, sid, tag, candidates
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
                                    cache_key = generate_cache_key(
                                        "udemy", tag, language
                                    )
                                    await cache.set(cache_key, winner)
                                    print(
                                        f"    🏆 [AI] Udemy Winner: {winner['title'][:50]}..."
                                    )
                    except Exception as e:
                        print(f"❌ [JOB {job_id[:8]}] Udemy Error: {e}")

                fetch_tasks.append(fetch_udemy_job())

            if fetch_tasks:
                await asyncio.gather(*fetch_tasks)

        if atomic_tags and CourseSource.YOUTUBE in active_sources:
            try:
                print(
                    f"    ⚛️ [JOB {job_id[:8]}] Fetching YouTube for atomic tags: {atomic_tags}"
                )
                sid = socket_server.get_socket_for_job(job_id) or current_sid
                youtube_data = await fetch_youtube(
                    sio,
                    sid,
                    atomic_tags,
                    language,
                    scope_cache=scope_cache,
                )
                roadmap_result["youtube"] = youtube_data
            except Exception as e:
                print(f"❌ [JOB {job_id[:8]}] YouTube (atomic) Error: {e}")

    print(f"🧬 [JOB {job_id[:8]}] Generating Learning DNA Sequence...")
    learning_path = generate_learning_path(tags, roadmap_data=roadmap_result)
    roadmap_result["learning_path"] = learning_path

    print(f"✅ [JOB {job_id[:8]}] Roadmap generation complete.")
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
        options.add_argument("--headless=new")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-default-apps")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument("--no-first-run")
        options.add_argument("--js-flags=--max-old-space-size=256")
        options.add_argument("--disable-background-timer-throttling")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--blink-settings=imagesEnabled=false")

        GLOBAL_DRIVER = uc.Chrome(options=options)
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
    job_id = request.job_id or uuid.uuid4().hex[:12]
    print(f"📥 [API] Incoming roadmap request — job_id: {job_id}")

    async with socket_server.job_semaphore:
        return await generate_roadmap_logic(
            tags=request.tags,
            prefer_paid=request.prefer_paid,
            language=request.language,
            sources=request.sources,
            job_id=job_id,
        )
