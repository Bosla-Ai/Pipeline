import os

# Set default test environment variables so legacy tests run in non-free HF / API modes
os.environ["FREE_HF_MODE"] = "false"
os.environ["YOUTUBE_FETCH_MODE"] = "api"
os.environ["DISABLE_YOUTUBE_API"] = "false"
os.environ["ENABLE_EXTERNAL_SCRAPERS"] = "true"
os.environ["ENABLE_UDEMY"] = "true"
os.environ["ENABLE_COURSERA"] = "true"
os.environ["ENABLE_BROWSER_SCRAPING"] = "true"

# Set socket timeout to 0 so tests don't hang and fail/pass immediately
os.environ["SOCKET_WAIT_TIMEOUT"] = "0"

# Skip global chrome driver initialization during test startup
os.environ["SKIP_GLOBAL_DRIVER_INIT"] = "true"
os.environ["ALLOW_DEV_AUTH_BYPASS"] = "true"
os.environ["PIPELINE_SHARED_SECRET"] = ""

from unittest.mock import AsyncMock
import src.utils.cache
import src.utils.event_log

# Mock connect to prevent network calls and timeouts when Redis is not running
src.utils.cache.cache.connect = AsyncMock()
src.utils.cache.cache._client = None

src.utils.event_log.event_log.connect = AsyncMock()
src.utils.event_log.event_log._redis_client = None
src.utils.event_log.event_log._use_redis = False

