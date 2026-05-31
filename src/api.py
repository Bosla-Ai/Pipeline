import asyncio
import os
import csv
import io
import uuid
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query, Header, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Optional

import src.socket_server as socket_server
from src.socket_server import sio

from src.utils.event_log import event_log
from src.engine.models import CourseSource

from src.config.settings import PIPELINE_SHARED_SECRET, DISABLE_YOUTUBE_API
from src.graph_inventory import runtime_contracts
from src.graph_inventory.runtime_contracts import ContractUnavailableError

from src.config import runtime_profile

if runtime_profile.FREE_HF_MODE:
    fetch_youtube = None
    fetch_coursera = None
else:
    from src.fetchers.videos.youtube_fetcher import fetch as fetch_youtube
    from src.fetchers.videos.coursera_fetcher import fetch_coursera

SOCKET_WAIT_TIMEOUT = int(os.environ.get("SOCKET_WAIT_TIMEOUT", "30"))


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


async def verify_pipeline_secret(
    x_pipeline_secret: Optional[str] = Header(None),
) -> None:
    """Dependency to verify the pipeline shared secret for API authentication."""
    if not PIPELINE_SHARED_SECRET:
        # If no secret is configured, require auth only in production
        if os.getenv("ENVIRONMENT") == "production":
            raise HTTPException(
                status_code=500,
                detail="PIPELINE_SHARED_SECRET must be configured in production",
            )
        # Allow all requests in development
        return
    if x_pipeline_secret != PIPELINE_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Invalid pipeline secret")


class RoadmapRequest(BaseModel):
    tags: List[str]
    prefer_paid: bool = False
    language: str = "en"
    sources: Optional[List[CourseSource]] = None
    tag_checkpoints: Optional[dict] = None
    job_id: Optional[str] = None


@app.get("/health")
async def health():
    """Public healthcheck endpoint returning simple status and service availability."""
    return {"status": "healthy"}


@app.get("/stats")
async def stats(_auth: None = Depends(verify_pipeline_secret)):
    """Return connected sockets, active jobs, connection details, and recent error count."""
    base = socket_server.get_stats()
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    recent_errors = await event_log.get_logs(since=cutoff, level="error", limit=1000)
    base["error_count_5m"] = len(recent_errors)
    return base


@app.get("/contracts/tag-contract")
async def get_tag_contract(_auth: None = Depends(verify_pipeline_secret)):
    """Expose the generated tag contract JSON."""
    try:
        return runtime_contracts.load_tag_contract()
    except ContractUnavailableError as exc:
        event_log.log(
            "error", "contracts", f"Contract load error: {exc.internal_message}"
        )
        raise HTTPException(status_code=500, detail=exc.public_message)


@app.get("/contracts/skill-inventory")
async def get_skill_inventory(_auth: None = Depends(verify_pipeline_secret)):
    """Expose the generated skill inventory JSON."""
    try:
        return runtime_contracts.load_skill_inventory()
    except ContractUnavailableError as exc:
        event_log.log(
            "error", "contracts", f"Contract load error: {exc.internal_message}"
        )
        raise HTTPException(status_code=500, detail=exc.public_message)


@app.get("/contracts/metadata")
async def get_contracts_metadata(_auth: None = Depends(verify_pipeline_secret)):
    """Expose lightweight metadata calculated from the generated contracts."""
    try:
        return runtime_contracts.get_contract_metadata()
    except ContractUnavailableError as exc:
        event_log.log(
            "error", "contracts", f"Contract load error: {exc.internal_message}"
        )
        raise HTTPException(status_code=500, detail=exc.public_message)


@app.get("/logs")
async def get_logs(
    since: Optional[str] = Query(None, description="ISO timestamp cutoff"),
    level: Optional[str] = Query(
        None, description="Filter by level: info, warn, error, success"
    ),
    category: Optional[str] = Query(None, description="Filter by category"),
    job_id: Optional[str] = Query(None, description="Filter by job ID"),
    limit: int = Query(200, ge=1, le=1000),
    _auth: None = Depends(verify_pipeline_secret),
):
    """Return pipeline event logs, newest first. Auto-cleaned after 24h."""
    return {
        "total": await event_log.get_count(),
        "logs": await event_log.get_logs(
            since=since, level=level, category=category, job_id=job_id, limit=limit
        ),
    }


@app.get("/logs/job/{job_id}")
async def get_job_logs(
    job_id: str,
    limit: int = Query(500, ge=1, le=2000),
    _auth: None = Depends(verify_pipeline_secret),
):
    """Return all log entries for a specific job, chronologically (oldest first)."""
    entries = await event_log.get_logs(job_id=job_id, limit=limit)
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
    _auth: None = Depends(verify_pipeline_secret),
):
    """Export logs as a downloadable JSON or CSV file."""
    entries = await event_log.get_logs(
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


from src.engine.roadmap_engine import RoadmapEngine


async def wait_for_socket(job_id: str) -> str | None:
    from src.engine.roadmap_engine import wait_for_socket as _wait_for_socket

    return await _wait_for_socket(job_id, timeout=SOCKET_WAIT_TIMEOUT)


GLOBAL_DRIVER = None
import asyncio

DRIVER_LOCK = asyncio.Lock()


@app.on_event("startup")
async def startup_event():
    global GLOBAL_DRIVER

    # Connect event_log and job_store to Redis
    await event_log.connect()
    from src.engine.job_store import job_store

    await job_store.connect()

    # Clean up stale active jobs on startup
    await cleanup_stale_jobs()

    # Start the 24h log cleanup background task
    event_log.start_cleanup_task()

    from src.config import runtime_profile

    # ── Udemy dependency readiness check ──
    if runtime_profile.ENABLE_UDEMY:
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
            event_log.log(
                "success", "system", "Udemy fetcher: Ready (all dependencies OK)"
            )
        else:
            missing = [k for k, v in udemy_deps.items() if not v]
            event_log.log(
                "error",
                "system",
                f"Udemy fetcher: NOT READY — missing modules: {', '.join(missing) if missing else 'import chain broken'}. "
                f"Try: pip install 'scrapling[fetchers]'",
            )
    else:
        event_log.log(
            "info", "system", "Udemy fetcher disabled (skipping readiness check)"
        )

    if (
        os.getenv("SKIP_GLOBAL_DRIVER_INIT") == "true"
        or runtime_profile.SKIP_GLOBAL_DRIVER_INIT
    ):
        event_log.log("warn", "driver", "Skipping driver init")
        return

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
    _auth: None = Depends(verify_pipeline_secret),
):
    """
    Search YouTube for an embeddable video matching the query.
    """
    if DISABLE_YOUTUBE_API:
        raise HTTPException(
            status_code=503,
            detail="YouTube API endpoints are disabled in production free-HF mode.",
        )
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
    _auth: None = Depends(verify_pipeline_secret),
):
    """
    Returns the list of videos in a playlist.
    """
    if DISABLE_YOUTUBE_API:
        raise HTTPException(
            status_code=503,
            detail="YouTube API endpoints are disabled in production free-HF mode.",
        )
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


from src.security.request_guard import validate_roadmap_request_data


@app.post("/generate-roadmap")
async def generate_roadmap(
    request: RoadmapRequest, _auth: None = Depends(verify_pipeline_secret)
):
    normalized_tags = validate_roadmap_request_data(
        tags=request.tags,
        language=request.language,
        sources=[s.value for s in request.sources] if request.sources else None,
        tag_checkpoints=request.tag_checkpoints,
        job_id=request.job_id,
    )
    job_id = request.job_id or uuid.uuid4().hex[:12]
    event_log.log("info", "job", f"Incoming roadmap request", job_id=job_id)

    from src.engine.job_store import job_store

    await job_store.create_job(
        job_id=job_id,
        tags=normalized_tags,
        language=request.language,
        prefer_paid=request.prefer_paid,
    )

    engine = RoadmapEngine(
        sio=sio,
        fetch_youtube=fetch_youtube,
        fetch_coursera=fetch_coursera,
        get_global_driver=lambda: GLOBAL_DRIVER,
        socket_wait_timeout=SOCKET_WAIT_TIMEOUT,
    )
    return await engine.generate(
        tags=normalized_tags,
        prefer_paid=request.prefer_paid,
        language=request.language,
        sources=request.sources,
        tag_checkpoints=request.tag_checkpoints,
        job_id=job_id,
    )


@app.get("/job/{job_id}")
async def get_job_status(
    job_id: str,
    _auth: None = Depends(verify_pipeline_secret),
):
    """Retrieve the status and result/error of a specific job."""
    from src.engine.job_store import job_store

    job = await job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


async def cleanup_stale_jobs():
    from src.engine.job_store import job_store

    try:
        active_job_ids = await job_store.get_active_jobs()
        for job_id in active_job_ids:
            job = await job_store.get_job(job_id)
            if job and job.get("status") in ("running", "pending"):
                await job_store.fail_job(job_id, "Job expired due to server restart")
                event_log.log(
                    "error",
                    "job",
                    f"Cleaned up stale running/pending job {job_id} on startup",
                    job_id=job_id,
                )
    except Exception as e:
        event_log.log(
            "error",
            "system",
            f"Stale job cleanup failed: {e}",
        )


async def verify_job_access(
    job_id: str,
    token: Optional[str] = Query(None),
    x_job_token: Optional[str] = Header(None, alias="X-Job-Token"),
    authorization: Optional[str] = Header(None),
    x_pipeline_secret: Optional[str] = Header(None, alias="X-Pipeline-Secret"),
):
    # Try pipeline secret authentication first
    if PIPELINE_SHARED_SECRET:
        if x_pipeline_secret == PIPELINE_SHARED_SECRET:
            return
    else:
        # In dev mode, allow bypass if the developer explicitly provided the secret header
        if os.getenv("ENVIRONMENT") != "production" and x_pipeline_secret is not None:
            return

    # Fallback to job token verification
    actual_token = token or x_job_token
    if (
        not actual_token
        and authorization
        and authorization.lower().startswith("bearer ")
    ):
        actual_token = authorization[7:]

    if not actual_token:
        raise HTTPException(
            status_code=401,
            detail="Missing job access token or pipeline secret",
        )

    from src.security.job_tokens import verify_token

    payload = verify_token(actual_token)
    if (
        not payload
        or payload.get("type") != "job_access"
        or payload.get("job_id") != job_id
    ):
        raise HTTPException(
            status_code=403,
            detail="Invalid or expired job access token",
        )


async def run_roadmap_job_bg(
    engine: RoadmapEngine,
    tags: List[str],
    prefer_paid: bool,
    language: str,
    sources: Optional[List[CourseSource]],
    tag_checkpoints: Optional[dict],
    job_id: str,
):
    try:
        await engine.generate(
            tags=tags,
            prefer_paid=prefer_paid,
            language=language,
            sources=sources,
            tag_checkpoints=tag_checkpoints,
            job_id=job_id,
        )
    except Exception as e:
        print(f"[BG Job] Job {job_id} failed: {e}")


@app.post("/jobs/roadmap")
async def post_jobs_roadmap(
    request: RoadmapRequest,
    _auth: None = Depends(verify_pipeline_secret),
):
    normalized_tags = validate_roadmap_request_data(
        tags=request.tags,
        language=request.language,
        sources=[s.value for s in request.sources] if request.sources else None,
        tag_checkpoints=request.tag_checkpoints,
        job_id=request.job_id,
    )
    job_id = request.job_id or uuid.uuid4().hex[:12]

    from src.engine.job_store import job_store
    from src.security.job_tokens import generate_job_access_token, generate_socket_token

    await job_store.create_job(
        job_id=job_id,
        tags=normalized_tags,
        language=request.language,
        prefer_paid=request.prefer_paid,
    )

    job_access_token = generate_job_access_token(job_id)
    socket_token = generate_socket_token(job_id)

    engine = RoadmapEngine(
        sio=sio,
        fetch_youtube=fetch_youtube,
        fetch_coursera=fetch_coursera,
        get_global_driver=lambda: GLOBAL_DRIVER,
        socket_wait_timeout=SOCKET_WAIT_TIMEOUT,
    )

    asyncio.create_task(
        run_roadmap_job_bg(
            engine=engine,
            tags=normalized_tags,
            prefer_paid=request.prefer_paid,
            language=request.language,
            sources=request.sources,
            tag_checkpoints=request.tag_checkpoints,
            job_id=job_id,
        )
    )

    return {
        "job_id": job_id,
        "status": "queued",
        "job_access_token": job_access_token,
        "socket_token": socket_token,
    }


@app.get("/jobs/{job_id}")
async def get_async_job(
    job_id: str,
    auth_check: None = Depends(verify_job_access),
):
    from src.engine.job_store import job_store

    job = await job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@app.get("/jobs/{job_id}/result")
async def get_async_job_result(
    job_id: str,
    auth_check: None = Depends(verify_job_access),
):
    from src.engine.job_store import job_store

    job = await job_store.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job["status"] != "completed":
        raise HTTPException(
            status_code=400, detail=f"Job is in state '{job['status']}', not completed"
        )
    return job["result"]
