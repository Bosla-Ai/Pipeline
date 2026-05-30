import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

################## Platforms ###############
# Youtube (filter out missing keys)
YOUTUBE_API_KEYS = [
    key for key in [os.getenv(f"YOUTUBE_API_KEY_{i}") for i in range(1, 13)] if key
]

# Udemy
UDEMY_CLIENT_ID = os.getenv("UDEMY_CLIENT_ID")
UDEMY_CLIENT_SECRET = os.getenv("UDEMY_CLIENT_SECRET")

# Google
GOOGLE_BOOKS_API_KEY = os.getenv("GOOGLE_BOOKS_API_KEY")

##################################################

################ HUGFace Models ##################

# Hugging Face API
HF_TOKEN = os.getenv("HF_TOKEN")

#################################################
# SQL Server connection
DB_CONNECTION_STRING = os.getenv("DB_CONNECTION_STRING", "")

# Import profile flags
from src.config.runtime_profile import (
    FREE_HF_MODE,
    YOUTUBE_FETCH_MODE,
    DISABLE_YOUTUBE_API,
    ENABLE_UDEMY,
    ENABLE_COURSERA,
    ENABLE_BROWSER_SCRAPING,
    SKIP_GLOBAL_DRIVER_INIT,
)

MAX_FETCH_RESULTS = int(os.getenv("MAX_FETCH_RESULTS", 10))
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en")

# Pipeline shared secret for API authentication
PIPELINE_SHARED_SECRET = os.getenv("PIPELINE_SHARED_SECRET")

# v2 Config limits
YT_DLP_MAX_RESULTS = int(os.getenv("YT_DLP_MAX_RESULTS", "6"))
YT_DLP_QUERY_LIMIT_PER_TAG = int(os.getenv("YT_DLP_QUERY_LIMIT_PER_TAG", "2"))
YT_DLP_HARD_TIMEOUT_SECONDS = int(os.getenv("YT_DLP_HARD_TIMEOUT_SECONDS", "15"))
MAX_TAGS = int(os.getenv("MAX_TAGS", "12"))
MAX_TAG_LENGTH = int(os.getenv("MAX_TAG_LENGTH", "120"))
MAX_TOTAL_TAG_CHARS = int(os.getenv("MAX_TOTAL_TAG_CHARS", "1500"))
