import os
import csv
import io
import asyncio
from datetime import datetime, timezone, timedelta
from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from src.utils.event_log import event_log

from src.config.settings import PIPELINE_SHARED_SECRET, DISABLE_YOUTUBE_API
from src.graph_inventory import runtime_contracts
from src.graph_inventory.runtime_contracts import ContractUnavailableError

from src.config import runtime_profile


app = FastAPI(title="Bosla Pipeline API")

from src.tools.router import router as tools_router

app.include_router(tools_router)

ALLOWED_API_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "ALLOWED_API_ORIGINS",
        "https://bosla.me,https://front.bosla.almiraj.xyz,http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_API_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Pipeline-Secret", "X-Job-Token"],
)


async def verify_pipeline_secret(
    x_pipeline_secret: Optional[str] = Header(None),
) -> None:
    """Dependency to verify the pipeline shared secret for API authentication."""
    if not PIPELINE_SHARED_SECRET:
        if (
            runtime_profile.FREE_HF_MODE
            or os.getenv("ENVIRONMENT") == "production"
            or os.getenv("ALLOW_DEV_AUTH_BYPASS") != "true"
        ):
            raise HTTPException(
                status_code=500,
                detail="PIPELINE_SHARED_SECRET must be configured",
            )
        return
    if x_pipeline_secret != PIPELINE_SHARED_SECRET:
        raise HTTPException(status_code=401, detail="Invalid pipeline secret")


@app.get("/health")
async def health():
    """Public healthcheck endpoint returning simple status and service availability."""
    return {"status": "healthy"}


@app.get("/stats")
async def stats(_auth: None = Depends(verify_pipeline_secret)):
    """Return service liveness and recent error count."""
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    recent_errors = await event_log.get_logs(since=cutoff, level="error", limit=1000)
    return {"status": "healthy", "error_count_5m": len(recent_errors)}


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


GLOBAL_DRIVER = None

DRIVER_LOCK = asyncio.Lock()


@app.on_event("startup")
async def startup_event():
    global GLOBAL_DRIVER

    await event_log.connect()

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
        except Exception:
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
