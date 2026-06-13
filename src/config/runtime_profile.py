import os
import importlib.util
from typing import Literal

# FREE_HF_MODE defaults to True as production deployment target is Free Hugging Face CPU Basic
FREE_HF_MODE = os.getenv("FREE_HF_MODE", "true").lower() == "true"

YOUTUBE_FETCH_MODE = os.getenv("YOUTUBE_FETCH_MODE", "yt_dlp")

ENABLE_EXTERNAL_SCRAPERS = (
    os.getenv("ENABLE_EXTERNAL_SCRAPERS", "false").lower() == "true"
)


def _is_module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


# Force values under FREE_HF_MODE, otherwise load from environment variables
if FREE_HF_MODE:
    DISABLE_YOUTUBE_API = True
    ENABLE_UDEMY = False
    ENABLE_COURSERA = False
    ENABLE_BROWSER_SCRAPING = False
    SKIP_GLOBAL_DRIVER_INIT = True
else:
    DISABLE_YOUTUBE_API = os.getenv("DISABLE_YOUTUBE_API", "true").lower() == "true"

    if ENABLE_EXTERNAL_SCRAPERS:
        udemy_deps_ok = _is_module_available("scrapling") and _is_module_available(
            "playwright"
        )
        coursera_deps_ok = _is_module_available(
            "undetected_chromedriver"
        ) and _is_module_available("selenium")

        ENABLE_UDEMY = (
            os.getenv("ENABLE_UDEMY", "false").lower() == "true" and udemy_deps_ok
        )
        ENABLE_COURSERA = (
            os.getenv("ENABLE_COURSERA", "false").lower() == "true" and coursera_deps_ok
        )
    else:
        ENABLE_UDEMY = False
        ENABLE_COURSERA = False

    ENABLE_BROWSER_SCRAPING = (
        os.getenv("ENABLE_BROWSER_SCRAPING", "false").lower() == "true"
        and ENABLE_EXTERNAL_SCRAPERS
    )
    SKIP_GLOBAL_DRIVER_INIT = (
        os.getenv("SKIP_GLOBAL_DRIVER_INIT", "false").lower() == "true"
        or not ENABLE_EXTERNAL_SCRAPERS
        or not ENABLE_COURSERA
    )
