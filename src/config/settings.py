import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

################## Platforms ###############
# Youtube
YOUTUBE_API_KEYS = [os.getenv(f"YOUTUBE_API_KEY_{i}") for i in range(1, 13)]

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

MAX_FETCH_RESULTS = int(os.getenv("MAX_FETCH_RESULTS", 10))
DEFAULT_LANGUAGE = os.getenv("DEFAULT_LANGUAGE", "en")
