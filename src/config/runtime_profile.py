import os
from typing import Literal

# FREE_HF_MODE defaults to True as production deployment target is Free Hugging Face CPU Basic
FREE_HF_MODE = os.getenv("FREE_HF_MODE", "true").lower() == "true"

YOUTUBE_FETCH_MODE = os.getenv("YOUTUBE_FETCH_MODE", "yt_dlp")

# Force values under FREE_HF_MODE, otherwise load from environment variables
if FREE_HF_MODE:
    DISABLE_YOUTUBE_API = True
    ENABLE_UDEMY = False
    ENABLE_COURSERA = False
    ENABLE_BROWSER_SCRAPING = False
    SKIP_GLOBAL_DRIVER_INIT = True
else:
    DISABLE_YOUTUBE_API = os.getenv("DISABLE_YOUTUBE_API", "true").lower() == "true"
    ENABLE_UDEMY = os.getenv("ENABLE_UDEMY", "false").lower() == "true"
    ENABLE_COURSERA = os.getenv("ENABLE_COURSERA", "false").lower() == "true"
    ENABLE_BROWSER_SCRAPING = (
        os.getenv("ENABLE_BROWSER_SCRAPING", "false").lower() == "true"
    )
    SKIP_GLOBAL_DRIVER_INIT = (
        os.getenv("SKIP_GLOBAL_DRIVER_INIT", "false").lower() == "true"
    )
