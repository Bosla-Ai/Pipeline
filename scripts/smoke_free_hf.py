import os
import sys
import asyncio
from httpx import AsyncClient

# Force FREE_HF_MODE=true and low socket wait timeout
os.environ["FREE_HF_MODE"] = "true"
os.environ["YOUTUBE_FETCH_MODE"] = "yt_dlp"
os.environ["SKIP_GLOBAL_DRIVER_INIT"] = "true"
os.environ["SOCKET_WAIT_TIMEOUT"] = "0"
os.environ["PIPELINE_SHARED_SECRET"] = "smoketestsecret"

from src.api import app

async def run_smoke_test():
    import httpx
    print("Starting Bosla Pipeline Free-HF Mode Smoke Test...")
    transport = httpx.ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.headers["X-Pipeline-Secret"] = "smoketestsecret"
        
        print("\n--- Testing /health ---")
        res = await client.get("/health")
        print(f"Status: {res.status_code}, Body: {res.json()}")
        assert res.status_code == 200
        
        print("\n--- Testing guard limits (too many tags) ---")
        res = await client.post(
            "/generate-roadmap",
            json={
                "tags": [f"t{i}" for i in range(13)],  # 13 tags (limit is 12)
                "prefer_paid": False,
                "language": "en"
            }
        )
        print(f"Status: {res.status_code}, Body: {res.json()}")
        assert res.status_code == 422
        
        print("\n--- Testing guard limits (tag too long) ---")
        long_tag = "a" * 121  # Max length is 120
        res = await client.post(
            "/generate-roadmap",
            json={
                "tags": [long_tag],
                "prefer_paid": False,
                "language": "en"
            }
        )
        print(f"Status: {res.status_code}, Body: {res.json()}")
        assert res.status_code == 422

        print("\n--- Testing async job creation via POST /jobs/roadmap ---")
        res = await client.post(
            "/jobs/roadmap",
            json={
                "tags": ["python coding basics"],
                "prefer_paid": False,
                "language": "en"
            }
        )
        print(f"Status: {res.status_code}, Body: {res.json()}")
        assert res.status_code == 200
        data = res.json()
        assert "job_id" in data
        assert data["status"] == "queued"
        assert "job_access_token" in data
        assert "socket_token" in data
        
        job_id = data["job_id"]
        token = data["job_access_token"]
        
        print("\n--- Testing GET /jobs/{job_id} without token (should fail) ---")
        client.headers.pop("X-Pipeline-Secret", None)
        res = await client.get(f"/jobs/{job_id}")
        print(f"Status: {res.status_code}")
        assert res.status_code == 401

        # Under FREE_HF_MODE, query-string token propagation is disabled (400);
        # the job token must be supplied via the X-Job-Token header.
        print("\n--- Testing GET /jobs/{job_id} with query token (disabled on FREE_HF -> 400) ---")
        res = await client.get(f"/jobs/{job_id}?token={token}")
        print(f"Status: {res.status_code}")
        assert res.status_code == 400

        print("\n--- Testing GET /jobs/{job_id} with invalid X-Job-Token (should fail) ---")
        res = await client.get(f"/jobs/{job_id}", headers={"X-Job-Token": "invalid"})
        print(f"Status: {res.status_code}")
        assert res.status_code == 403

        print("\n--- Testing GET /jobs/{job_id} with valid X-Job-Token (should succeed) ---")
        res = await client.get(f"/jobs/{job_id}", headers={"X-Job-Token": token})
        print(f"Status: {res.status_code}, Body: {res.json()}")
        assert res.status_code == 200
        assert res.json()["job_id"] == job_id

        # Poll for job completion
        import time
        print("\n--- Polling GET /jobs/{job_id} for completion ---")
        start_time = time.time()
        job_data = res.json()
        while time.time() - start_time < 30:
            res = await client.get(f"/jobs/{job_id}", headers={"X-Job-Token": token})
            assert res.status_code == 200
            job_data = res.json()
            status = job_data.get("status")
            print(f"Job Status: {status}")
            if status in ("completed", "failed"):
                break
            await asyncio.sleep(0.5)

        assert job_data.get("status") == "completed", f"Job did not complete: {job_data}"
        result = job_data.get("result")
        assert result is not None
        data = result.get("data")
        assert data is not None, f"Expected 'data' key in result: {result}"

        print("\n--- Asserting result structure ---")
        assert "youtube" in data
        assert data.get("udemy") == {}
        assert data.get("coursera") == {}

        # Assert that youtube returns a valid URL
        youtube_data = data["youtube"]
        found_url = False
        for tag_key, tag_res in youtube_data.items():
            if isinstance(tag_res, list):
                for item in tag_res:
                    if "url" in item and item["url"]:
                        found_url = True
            elif isinstance(tag_res, dict) and tag_res.get("url"):
                found_url = True
        assert found_url, f"Expected non-empty YouTube URL in youtube results: {youtube_data}"

        # Restore header for next steps
        client.headers["X-Pipeline-Secret"] = "smoketestsecret"
        
        # Under FREE_HF_MODE=true, /search-embeddable-video and /youtube/playlist-items return 503
        print("\n--- Testing /search-embeddable-video (should fail with 503 on FREE_HF) ---")
        res = await client.get("/search-embeddable-video?q=react&lang=en")
        print(f"Status: {res.status_code}, Body: {res.json()}")
        assert res.status_code == 503

        print("\n--- Testing /youtube/playlist-items (should fail with 503 on FREE_HF) ---")
        res = await client.get("/youtube/playlist-items?playlistId=123")
        print(f"Status: {res.status_code}, Body: {res.json()}")
        assert res.status_code == 503

        print("\n✅ Smoke test passed successfully!")

if __name__ == "__main__":
    from unittest.mock import patch
    mock_entry = {
        "id": "mock_yt_123",
        "title": "Python coding basics full course",
        "url": "https://www.youtube.com/watch?v=mock_yt_123",
        "duration": 600,
        "view_count": 1000,
        "like_count": 100,
        "upload_date": "20230101",
    }
    try:
        with patch("src.fetchers.videos.youtube_scraper._extract_search_results", return_value=[mock_entry]):
            asyncio.run(run_smoke_test())
        sys.exit(0)
    except AssertionError as e:
        print(f"\n Smoke test failed: Assertion failed.", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"\n Smoke test failed with exception: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
