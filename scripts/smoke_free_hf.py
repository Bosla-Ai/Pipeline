import os
import sys

# Force FREE_HF_MODE=true and low socket wait timeout
os.environ["FREE_HF_MODE"] = "true"
os.environ["YOUTUBE_FETCH_MODE"] = "yt_dlp"
os.environ["SKIP_GLOBAL_DRIVER_INIT"] = "true"
os.environ["SOCKET_WAIT_TIMEOUT"] = "0"
os.environ["PIPELINE_SHARED_SECRET"] = "smoketestsecret"

from fastapi.testclient import TestClient
from src.api import app

def run_smoke_test():
    print("Starting Bosla Pipeline Free-HF Mode Smoke Test...")
    client = TestClient(app)
    client.headers["X-Pipeline-Secret"] = "smoketestsecret"
    
    print("\n--- Testing /health ---")
    res = client.get("/health")
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 200
    
    print("\n--- Testing guard limits (too many tags) ---")
    res = client.post(
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
    res = client.post(
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
    res = client.post(
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
    res = client.get(f"/jobs/{job_id}")
    print(f"Status: {res.status_code}")
    assert res.status_code == 401

    print("\n--- Testing GET /jobs/{job_id} with invalid token (should fail) ---")
    res = client.get(f"/jobs/{job_id}?token=invalid")
    print(f"Status: {res.status_code}")
    assert res.status_code == 403

    print("\n--- Testing GET /jobs/{job_id} with valid token (should succeed) ---")
    res = client.get(f"/jobs/{job_id}?token={token}")
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 200
    assert res.json()["job_id"] == job_id
    
    # Restore header for next steps
    client.headers["X-Pipeline-Secret"] = "smoketestsecret"
    
    # Under FREE_HF_MODE=true, /search-embeddable-video and /youtube/playlist-items return 503
    print("\n--- Testing /search-embeddable-video (should fail with 503 on FREE_HF) ---")
    res = client.get("/search-embeddable-video?q=react&lang=en")
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 503

    print("\n--- Testing /youtube/playlist-items (should fail with 503 on FREE_HF) ---")
    res = client.get("/youtube/playlist-items?playlistId=123")
    print(f"Status: {res.status_code}, Body: {res.json()}")
    assert res.status_code == 503

    print("\n✅ Smoke test passed successfully!")

if __name__ == "__main__":
    try:
        run_smoke_test()
        sys.exit(0)
    except AssertionError as e:
        print(f"\n Smoke test failed: Assertion failed.", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"\n Smoke test failed with exception: {e}", file=sys.stderr)
        sys.exit(1)
