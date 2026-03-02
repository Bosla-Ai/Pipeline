import asyncio
import os
import csv
import io
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
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
from src.utils.event_log import event_log

app = FastAPI(title="Bosla Pipeline API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://bosla.me",
        "https://front.bosla.almiraj.xyz",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    tag_checkpoints: Optional[dict] = None
    job_id: Optional[str] = None


@app.get("/stats")
async def stats():
    """Return connected sockets, active jobs, connection details, and recent error count."""
    base = socket_server.get_stats()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    recent_errors = event_log.get_logs(since=cutoff, level="error", limit=1000)
    base["error_count_5m"] = len(recent_errors)
    return base


@app.get("/logs")
async def get_logs(
    since: Optional[str] = Query(None, description="ISO timestamp cutoff"),
    level: Optional[str] = Query(
        None, description="Filter by level: info, warn, error, success"
    ),
    category: Optional[str] = Query(None, description="Filter by category"),
    job_id: Optional[str] = Query(None, description="Filter by job ID"),
    limit: int = Query(200, ge=1, le=1000),
):
    """Return pipeline event logs, newest first. Auto-cleaned after 24h."""
    return {
        "total": event_log.count,
        "logs": event_log.get_logs(
            since=since, level=level, category=category, job_id=job_id, limit=limit
        ),
    }


@app.get("/logs/job/{job_id}")
async def get_job_logs(job_id: str, limit: int = Query(500, ge=1, le=2000)):
    """Return all log entries for a specific job, chronologically (oldest first)."""
    entries = event_log.get_logs(job_id=job_id, limit=limit)
    # get_logs returns newest first; reverse for timeline order
    return {"job_id": job_id, "total": len(entries), "logs": list(reversed(entries))}


@app.get("/logs/export")
async def export_logs(
    fmt: str = Query("json", description="Export format: json or csv"),
    since: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    job_id: Optional[str] = Query(None),
    limit: int = Query(1000, ge=1, le=5000),
):
    """Export logs as a downloadable JSON or CSV file."""
    entries = event_log.get_logs(
        since=since, level=level, category=category, job_id=job_id, limit=limit
    )

    if fmt == "csv":
        buf = io.StringIO()
        writer = csv.DictWriter(
            buf,
            fieldnames=["id", "timestamp", "level", "category", "message", "job_id"],
        )
        writer.writeheader()
        for e in entries:
            writer.writerow({k: e.get(k, "") for k in writer.fieldnames})
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=pipeline_logs.csv"},
        )

    # Default: JSON
    import json as _json

    content = _json.dumps(entries, indent=2)
    return StreamingResponse(
        io.BytesIO(content.encode()),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=pipeline_logs.json"},
    )


SOCKET_WAIT_TIMEOUT = int(os.environ.get("SOCKET_WAIT_TIMEOUT", "30"))


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
        event_log.log(
            "warn",
            "job",
            f"No frontend socket connected within {SOCKET_WAIT_TIMEOUT}s. Proceeding without AI.",
            job_id=job_id,
        )
        return None
    finally:
        socket_server.cleanup_job_waiter(job_id)


async def generate_roadmap_logic(
    tags: List[str],
    prefer_paid: bool,
    language: str,
    sources: Optional[List[CourseSource]] = None,
    tag_checkpoints: Optional[dict] = None,
    job_id: Optional[str] = None,
):
    if not job_id:
        job_id = uuid.uuid4().hex[:12]

    tags = preprocess_tags(tags)

    event_log.log(
        "info",
        "job",
        f"Roadmap requested. Tags: {tags}, Lang: {language}",
        job_id=job_id,
    )
    event_log.log("info", "job", "Waiting for frontend socket…", job_id=job_id)

    current_sid = await wait_for_socket(job_id)

    if current_sid:
        event_log.log(
            "success",
            "job",
            f"Frontend socket ready (sid: {current_sid})",
            job_id=job_id,
        )
    else:
        event_log.log(
            "warn",
            "job",
            "No frontend socket. AI classification will be skipped.",
            job_id=job_id,
        )

    roadmap_result = {"youtube": {}, "coursera": {}, "udemy": {}}

    if sources:
        active_sources = sources
        if prefer_paid:
            # Strip free sources when user explicitly prefers paid;
            # YouTube is still used as fallback for atomic / unmatched tags later.
            paid_only = [s for s in active_sources if s != CourseSource.YOUTUBE]
            if paid_only:
                active_sources = paid_only
    elif prefer_paid:
        active_sources = [CourseSource.UDEMY]
    else:
        active_sources = [CourseSource.YOUTUBE]

    event_log.log("info", "job", f"Active Sources: {active_sources}", job_id=job_id)

    if CourseSource.YOUTUBE in active_sources:
        try:
            event_log.log(
                "info",
                "fetcher",
                f"Fetching Free Content (YouTube)... Lang: {language}",
                job_id=job_id,
            )
            youtube_data = await fetch_youtube(sio, current_sid, tags, language)
            roadmap_result["youtube"] = youtube_data
        except Exception as e:
            event_log.log(
                "error", "fetcher", f"YouTube fetcher error: {e}", job_id=job_id
            )

    paid_sources_requested = any(
        s in active_sources for s in [CourseSource.COURSERA, CourseSource.UDEMY]
    )

    if paid_sources_requested:
        event_log.log(
            "info", "fetcher", f"Fetching Paid Content | Tags: {tags}", job_id=job_id
        )

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

        event_log.log(
            "info",
            "job",
            f"Scope: Broad={broad_tags}, Atomic={atomic_tags}",
            job_id=job_id,
            details={
                "broad_tags": broad_tags,
                "atomic_tags": atomic_tags,
                "method": "heuristic+ai_fallback",
            },
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
                        event_log.log(
                            "error", "fetcher", f"Coursera Error: {e}", job_id=job_id
                        )

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
                                event_log.log(
                                    "success",
                                    "cache",
                                    f"Cache Hit - Udemy: {tag}",
                                    job_id=job_id,
                                )
                                udemy_cached[tag] = cached_result
                            else:
                                udemy_tags_to_fetch.append(tag)

                        roadmap_result["udemy"] = udemy_cached

                        if not udemy_tags_to_fetch:
                            event_log.log(
                                "success",
                                "cache",
                                "Udemy: All tags cached",
                                job_id=job_id,
                            )
                        else:
                            udemy_fetcher = UdemyFetcher(
                                tags=udemy_tags_to_fetch,
                                limit=5,
                                headless=True,
                            )
                            await asyncio.to_thread(udemy_fetcher.scrape)

                            # Log Cloudflare blocks for dashboard visibility
                            if udemy_fetcher.blocked_tags:
                                event_log.log(
                                    "warn",
                                    "fetcher",
                                    f"Cloudflare blocked Udemy for: {udemy_fetcher.blocked_tags}",
                                    job_id=job_id,
                                    details={
                                        "source": "udemy",
                                        "blocked_tags": udemy_fetcher.blocked_tags,
                                        "reason": "cloudflare_waf",
                                    },
                                )

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
                                    event_log.log(
                                        "warn",
                                        "fetcher",
                                        f"No AI selection for '{tag}', using fallback.",
                                        job_id=job_id,
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
                                    event_log.log(
                                        "success",
                                        "fetcher",
                                        f"Udemy Winner: {winner['title'][:50]}...",
                                        job_id=job_id,
                                    )
                    except Exception as e:
                        event_log.log(
                            "error", "fetcher", f"Udemy Error: {e}", job_id=job_id
                        )

                fetch_tasks.append(fetch_udemy_job())

            if fetch_tasks:
                await asyncio.gather(*fetch_tasks)

        if atomic_tags:
            # Always fall back to YouTube for atomic tags — even in paid mode,
            # atomic topics (specific concepts) are best served by free videos.
            try:
                event_log.log(
                    "info",
                    "fetcher",
                    f"Fetching YouTube for atomic tags: {atomic_tags}",
                    job_id=job_id,
                )
                sid = socket_server.get_socket_for_job(job_id) or current_sid
                youtube_data = await fetch_youtube(
                    sio,
                    sid,
                    atomic_tags,
                    language,
                    scope_cache=scope_cache,
                )
                roadmap_result["youtube"].update(youtube_data)
            except Exception as e:
                event_log.log(
                    "error", "fetcher", f"YouTube (atomic) Error: {e}", job_id=job_id
                )

        # ── Fallback: if paid sources returned nothing for broad tags, use YouTube ──
        if broad_tags:
            unmatched_broad = [
                t
                for t in broad_tags
                if t not in (roadmap_result.get("udemy") or {})
                and t not in (roadmap_result.get("coursera") or {})
            ]
            if unmatched_broad:
                event_log.log(
                    "warn",
                    "fetcher",
                    f"Paid sources returned nothing for {unmatched_broad}. Falling back to YouTube.",
                    job_id=job_id,
                    details={
                        "fallback": "youtube",
                        "unmatched_tags": unmatched_broad,
                        "active_sources": [s.value for s in active_sources],
                    },
                )
                try:
                    sid = socket_server.get_socket_for_job(job_id) or current_sid
                    youtube_fallback = await fetch_youtube(
                        sio, sid, unmatched_broad, language, scope_cache=scope_cache
                    )
                    roadmap_result["youtube"].update(youtube_fallback)

                    fb_found = [
                        t
                        for t in unmatched_broad
                        if t in youtube_fallback and youtube_fallback[t]
                    ]
                    fb_missed = [t for t in unmatched_broad if t not in fb_found]
                    if fb_found:
                        event_log.log(
                            "success",
                            "fetcher",
                            f"YouTube fallback found resources for: {fb_found}",
                            job_id=job_id,
                            details={
                                "fallback_found": fb_found,
                                "fallback_missed": fb_missed,
                            },
                        )
                    if fb_missed:
                        event_log.log(
                            "warn",
                            "fetcher",
                            f"YouTube fallback found nothing for: {fb_missed}",
                            job_id=job_id,
                            details={"fallback_missed": fb_missed},
                        )
                except Exception as e:
                    event_log.log(
                        "error",
                        "fetcher",
                        f"YouTube fallback Error: {e}",
                        job_id=job_id,
                    )

    event_log.log("info", "job", "Generating Learning DNA Sequence...", job_id=job_id)
    learning_path = generate_learning_path(
        tags, roadmap_data=roadmap_result, tag_checkpoints=tag_checkpoints
    )
    roadmap_result["learning_path"] = learning_path

    event_log.log("success", "job", "Roadmap generation complete.", job_id=job_id)

    # ── Resource Audit: log every tag's resource status ───────────────
    _audit_found = 0
    _audit_missing = []
    _audit_no_url = []

    for source_name in ("youtube", "udemy", "coursera"):
        src_map = roadmap_result.get(source_name, {})
        for key, resource in (src_map or {}).items():
            if resource is None:
                continue
            if not isinstance(resource, dict):
                continue
            url = resource.get("url", "")
            title = str(resource.get("title", ""))[:60]
            has_url = isinstance(url, str) and url.startswith(("http://", "https://"))
            event_log.log(
                "info",
                "resource_audit",
                f"[{source_name.upper()}] tag='{key}' | title='{title}' | url={'YES' if has_url else 'MISSING'}",
                job_id=job_id,
            )
            if has_url:
                _audit_found += 1
            else:
                _audit_no_url.append(f"{source_name}:{key}")

    # Check which tags from the roadmap have NO resource at all
    lp = roadmap_result.get("learning_path", {})
    for phase in lp.get("phases", []):
        for tag_info in phase.get("tags", []):
            if not tag_info.get("has_resource", False):
                _audit_missing.append(tag_info.get("tag", "?"))

    if _audit_missing:
        event_log.log(
            "warn",
            "resource_audit",
            f"Tags with NO matching resource ({len(_audit_missing)}): {_audit_missing}",
            job_id=job_id,
        )
    if _audit_no_url:
        event_log.log(
            "warn",
            "resource_audit",
            f"Resources with MISSING url ({len(_audit_no_url)}): {_audit_no_url}",
            job_id=job_id,
        )
    event_log.log(
        "info",
        "resource_audit",
        f"Audit summary: {_audit_found} resources with url, "
        f"{len(_audit_no_url)} without url, {len(_audit_missing)} tags unmatched.",
        job_id=job_id,
    )

    # Safety net: normalize resource objects so `url` is present when possible.
    # This prevents downstream clients from rendering resources without links.
    def _is_http_url(v):
        return isinstance(v, str) and v.startswith(("http://", "https://"))

    def _normalize_source_map(source_name: str, source_map: dict):
        if not isinstance(source_map, dict):
            return

        for key, resource in source_map.items():
            if resource is None:
                continue

            if not isinstance(resource, dict):
                # Unexpected shape — don't crash the job; just log for debugging.
                try:
                    event_log.log(
                        "warn",
                        "job",
                        f"Resource for '{key}' in {source_name} is not an object ({type(resource).__name__}).",
                        job_id=job_id,
                    )
                except Exception:
                    pass
                continue

            url = resource.get("url")
            if _is_http_url(url):
                continue

            # If dict key is actually a URL (some flows key by url)
            if _is_http_url(key):
                resource["url"] = key
                continue

            content_id = resource.get("contentId")
            if _is_http_url(content_id):
                resource["url"] = content_id
                continue

            # Best-effort YouTube reconstruction
            if source_name == "youtube" and isinstance(content_id, str) and content_id:
                ct = str(resource.get("contentType") or "").lower()
                if ct == "playlist":
                    resource["url"] = (
                        f"https://www.youtube.com/playlist?list={content_id}"
                    )
                elif ct == "video":
                    resource["url"] = f"https://www.youtube.com/watch?v={content_id}"

            # Still no url → log once per item (warn)
            if not _is_http_url(resource.get("url")):
                try:
                    event_log.log(
                        "warn",
                        "job",
                        f"Missing url for resource '{key}' in {source_name}.",
                        job_id=job_id,
                    )
                except Exception:
                    pass

    for _src in ("youtube", "udemy", "coursera"):
        _normalize_source_map(_src, roadmap_result.get(_src, {}))

    return {"status": "success", "data": roadmap_result}


GLOBAL_DRIVER = None
import asyncio

DRIVER_LOCK = asyncio.Lock()


@app.on_event("startup")
async def startup_event():
    global GLOBAL_DRIVER

    # Start the 24h log cleanup background task
    event_log.start_cleanup_task()

    # ── Udemy dependency readiness check ──
    udemy_deps = {
        "scrapling": False,
        "curl_cffi": False,
        "playwright": False,
        "patchright": False,
        "browserforge": False,
    }
    for dep in udemy_deps:
        try:
            __import__(dep)
            udemy_deps[dep] = True
        except ImportError:
            pass

    # Final validation: try the actual import chain the scraper uses
    try:
        from scrapling.fetchers import AsyncStealthySession  # noqa: F401

        udemy_ready = True
    except Exception:
        udemy_ready = False

    if udemy_ready:
        event_log.log("success", "system", "Udemy fetcher: Ready (all dependencies OK)")
    else:
        missing = [k for k, v in udemy_deps.items() if not v]
        event_log.log(
            "error",
            "system",
            f"Udemy fetcher: NOT READY — missing modules: {', '.join(missing) if missing else 'import chain broken'}. "
            f"Try: pip install 'scrapling[fetchers]'",
        )

    try:
        import subprocess
        import re as _re
        import undetected_chromedriver as uc

        event_log.log("info", "driver", "Initializing Global Chrome Driver...")

        # Detect installed Chrome major version so ChromeDriver always matches
        version_main = None
        try:
            out = subprocess.check_output(
                ["google-chrome", "--version"], text=True
            ).strip()
            m = _re.search(r"(\d+)\.", out)
            if m:
                version_main = int(m.group(1))
                event_log.log(
                    "info", "driver", f"Detected Chrome {version_main} ({out})"
                )
        except Exception:
            event_log.log(
                "warn",
                "driver",
                "Could not detect Chrome version, letting uc auto-detect",
            )

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

        GLOBAL_DRIVER = uc.Chrome(options=options, version_main=version_main)
        event_log.log("success", "driver", "Global Driver Initialized & Ready")
    except Exception as e:
        event_log.log("error", "driver", f"Driver Init Failed: {e}")


@app.on_event("shutdown")
def shutdown_event():
    global GLOBAL_DRIVER
    if GLOBAL_DRIVER:
        event_log.log("info", "driver", "Shutting down Global Driver...")
        try:
            GLOBAL_DRIVER.quit()
        except:
            pass


@app.get("/search-embeddable-video")
async def search_embeddable_video_endpoint(
    q: str = Query(..., description="Search query for the video"),
    lang: str = Query("en", description="Language preference: en or ar"),
):
    """
    Search YouTube for an embeddable video matching the query.
    """
    from src.fetchers.videos.youtube_fetcher import search_embeddable_video

    event_log.log(
        "info", "video_search", f"Searching embeddable video: q='{q}', lang='{lang}'"
    )

    result = await search_embeddable_video(q, lang)

    if result is None:
        event_log.log("warn", "video_search", f"No embeddable video found for: '{q}'")
        return {"status": "not_found", "message": "No embeddable videos found"}

    event_log.log(
        "success",
        "video_search",
        f"Found embeddable video: '{result.get('title', '?')[:60]}' | Views: {result.get('viewCount', '?')} | URL: {result.get('url', '?')}",
    )
    return {"status": "ok", **result}


PLAYLIST_ITEMS_URL = "https://www.googleapis.com/youtube/v3/playlistItems"


@app.get("/youtube/playlist-items")
async def youtube_playlist_items(
    playlistId: str = Query(..., description="YouTube playlist ID"),
    maxResults: int = Query(50, ge=1, le=50, description="Max items to return"),
):
    """
    Returns the list of videos in a playlist.
    """
    import aiohttp
    from src.fetchers.videos.youtube_fetcher import fetch_youtube_data

    event_log.log(
        "info",
        "playlist_proxy",
        f"Fetching playlist items: playlistId='{playlistId}', maxResults={maxResults}",
    )

    params = {
        "part": "snippet",
        "playlistId": playlistId,
        "maxResults": str(maxResults),
    }

    async with aiohttp.ClientSession() as session:
        data = await fetch_youtube_data(session, PLAYLIST_ITEMS_URL, params)

    if not data or "items" not in data:
        event_log.log(
            "warn", "playlist_proxy", f"No items found for playlist: '{playlistId}'"
        )
        raise HTTPException(status_code=404, detail="Playlist not found or empty")

    items = [
        {
            "id": item["snippet"]["resourceId"]["videoId"],
            "title": item["snippet"]["title"],
            "thumbnailUrl": (
                item["snippet"].get("thumbnails", {}).get("medium", {}).get("url")
                or item["snippet"].get("thumbnails", {}).get("default", {}).get("url")
            ),
        }
        for item in data.get("items", [])
        if item.get("snippet", {}).get("resourceId", {}).get("videoId")
    ]

    event_log.log(
        "success",
        "playlist_proxy",
        f"Returned {len(items)} items for playlist: '{playlistId}'",
    )
    return {"status": "ok", "items": items}


@app.post("/generate-roadmap")
async def generate_roadmap(request: RoadmapRequest):
    job_id = request.job_id or uuid.uuid4().hex[:12]
    event_log.log("info", "job", f"Incoming roadmap request", job_id=job_id)

    async with socket_server.job_semaphore:
        return await generate_roadmap_logic(
            tags=request.tags,
            prefer_paid=request.prefer_paid,
            language=request.language,
            sources=request.sources,
            tag_checkpoints=request.tag_checkpoints,
            job_id=job_id,
        )
