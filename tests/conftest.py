import os

# Set default test environment variables so legacy tests run in non-free HF / API modes
os.environ["FREE_HF_MODE"] = "false"
os.environ["YOUTUBE_FETCH_MODE"] = "api"
os.environ["DISABLE_YOUTUBE_API"] = "false"
os.environ["ENABLE_UDEMY"] = "true"
os.environ["ENABLE_COURSERA"] = "true"
os.environ["ENABLE_BROWSER_SCRAPING"] = "true"

# Set socket timeout to 0 so tests don't hang and fail/pass immediately
os.environ["SOCKET_WAIT_TIMEOUT"] = "0"

# Skip global chrome driver initialization during test startup
os.environ["SKIP_GLOBAL_DRIVER_INIT"] = "true"
