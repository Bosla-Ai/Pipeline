---
title: "Bosla Pipeline"
emoji: "🧭"
colorFrom: "blue"
colorTo: "indigo"
sdk: "docker"
pinned: false
license: "mit"
app_port: 7860
---

# BoslaPipeline

BoslaPipeline is the AI-powered content aggregation service for the [Bosla platform](https://github.com/Bosla-Ai/), designed to fetch, process, and classify learning resources from multiple sources. Built with FastAPI and Socket.IO, it provides real-time content recommendations and integrates with HuggingFace for AI-assisted classification.

[![Python](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/fastapi-latest-009688.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

## Technology Stack

The project leverages the following technologies and frameworks:

| Category | Technologies |
|----------|-------------|
| **Core** | Python 3.11, FastAPI, Uvicorn |
| **Real-time** | Socket.IO (python-socketio) |
| **Caching** | Redis |
| **Scraping** | Selenium, undetected-chromedriver, BeautifulSoup4, Scrapling |
| **HTTP** | aiohttp, requests |
| **Video** | yt-dlp (YouTube scraping fallback) |
| **Validation** | Pydantic |
| **Configuration** | python-dotenv |
| **Testing** | pytest, pytest-asyncio |
| **Code Quality** | Black (formatter) |
| **Deployment** | Docker, HuggingFace Spaces |

## Architecture

The solution is structured as a modular pipeline:

```
BoslaPipeline/
├── src/
│   ├── main.py                 # Application entry point (FastAPI + Socket.IO)
│   ├── api.py                  # REST API endpoints
│   ├── socket_server.py        # Real-time Socket.IO handlers
│   │
│   ├── config/
│   │   └── settings.py         # Configuration & environment variables
│   │
│   ├── fetchers/               # Data source integrations
│   │   ├── videos/
│   │   │   ├── youtube_fetcher.py    # YouTube Data API + scraper fallback
│   │   │   ├── youtube_scraper.py    # yt-dlp based scraper
│   │   │   ├── udemy_fetcher.py      # Udemy course scraper
│   │   │   └── coursera_fetcher.py   # Coursera integration
│   │   └── scraping_utils.py   # Shared scraping utilities
│   │
│   └── utils/                  # Shared utilities
│       ├── cache.py            # Redis caching layer
│       ├── scoring.py          # Resource ranking algorithms
│       ├── helpers.py          # AI classification helpers
│       ├── key_manager.py      # API key rotation
│       ├── learning_path.py    # Learning path generation
│       ├── event_log.py        # Pipeline event logging
│       ├── constants.py        # Tag mappings & keywords
│       └── logger.py           # Logging configuration
│
└── tests/                      # Unit & integration tests
```

### Key Components

* **API Layer** (`api.py`): FastAPI endpoints for roadmap generation and resource search
* **Socket Server** (`socket_server.py`): Real-time communication with frontend for AI classification
* **Fetchers**: Source-specific modules that retrieve and normalize content
* **Scoring Engine** (`scoring.py`): Ranks resources based on quality metrics
* **Cache Layer** (`cache.py`): Redis-backed caching for API responses

## Features

* Fetch data from multiple sources: **YouTube, Udemy, Coursera**
* **API key rotation** for YouTube quota management (12 keys supported)
* **Fallback scraping** via yt-dlp when API quota exhausted
* **Real-time AI classification** via frontend Socket.IO bridge
* **Smart caching** with Redis for reduced API calls
* **Configurable scoring** based on views, likes, subscribers, and content length
* **Event logging** with automatic 24-hour cleanup

## Prerequisites

Before getting started, ensure you have the following installed:

* [Python 3.11](https://www.python.org/downloads/) (required - 3.12+ not compatible with undetected-chromedriver)
* [Redis](https://redis.io/download) (for caching)
* [Google Chrome](https://www.google.com/chrome/) (for headless scraping)
* [Xvfb](https://www.x.org/releases/X11R7.6/doc/man/man1/Xvfb.1.xhtml) (for headless display on Linux)
* [Git](https://git-scm.com/)

### API Keys Required

| Service | Purpose | How to Obtain |
|---------|---------|---------------|
| YouTube Data API v3 | Video/playlist search | [Google Cloud Console](https://console.cloud.google.com/apis/credentials) |
| HuggingFace Token | AI model access | [HuggingFace Settings](https://huggingface.co/settings/tokens) |
| Udemy Affiliate API | Course data (optional) | [Udemy Affiliate Program](https://www.udemy.com/affiliate/) |

## Getting Started

For detailed platform-specific instructions, refer to the [Development Setup guide in CONTRIBUTING.md](CONTRIBUTING.md#development-setup).

### 1. Clone the Repository

```bash
git clone https://github.com/Bosla-Ai/BoslaPipeline.git
cd BoslaPipeline
```

### 2. Install System Dependencies

#### Ubuntu/Debian

```bash
sudo apt update && sudo apt upgrade
sudo apt install python3.11 python3.11-venv xvfb redis-server
```

#### Fedora

```bash
sudo dnf update
sudo dnf install python3.11 xorg-x11-server-Xvfb redis
```

### 3. Create Virtual Environment

```bash
python3.11 -m venv venv
source venv/bin/activate  # Linux/macOS
# or: venv\Scripts\activate  # Windows
```

### 4. Install Python Dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure Environment Variables

Create a `.env` file based on the provided template:

```bash
cp .env.example .env
```

Update the `.env` file with your configuration:

```env
# YouTube API Keys (supports up to 12 for rotation)
YOUTUBE_API_KEY_1=your_key_here
YOUTUBE_API_KEY_2=your_key_here
# ... add more as needed

# HuggingFace
HF_TOKEN=your_huggingface_token

# Optional: Udemy
UDEMY_CLIENT_ID=your_client_id
UDEMY_CLIENT_SECRET=your_client_secret

# Optional: Database
DB_CONNECTION_STRING=mssql+pyodbc://user:pass@server/db?driver=ODBC+Driver+17+for+SQL+Server

# Configuration
MAX_FETCH_RESULTS=10
DEFAULT_LANGUAGE=en
REDIS_HOST=localhost
```

### 6. Start Redis

```bash
redis-server --daemonize yes
```

### 7. Run the Application

```bash
python -m src.main
```

The server will be available at `http://localhost:7860`.

## API Documentation

FastAPI provides automatic interactive documentation:

| Endpoint | Description |
|----------|-------------|
| `http://localhost:7860/docs` | Swagger UI (interactive) |
| `http://localhost:7860/redoc` | ReDoc (read-only) |

### Key Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/generate-roadmap` | Generate learning roadmap for tags |
| GET | `/stats` | Server statistics and health |
| GET | `/logs` | Pipeline event logs |
| GET | `/search-embeddable-video` | Search for embeddable YouTube video |
| GET | `/youtube/playlist-items` | Get playlist video items |

## Docker Deployment

The project includes a Dockerfile optimized for HuggingFace Spaces:

```bash
docker build -t bosla-pipeline .
docker run -p 7860:7860 --env-file .env bosla-pipeline
```

## Testing

Unit tests are in the `tests/` directory:

```bash
# Run all tests
pytest tests/

# Run with coverage
pytest tests/ --cov=src

# Run in parallel
pytest tests/ -n auto
```

## Configuration

All sensitive data and configurable parameters are loaded from environment variables via `src/config/settings.py`:

| Variable | Description | Default |
|----------|-------------|---------|
| `YOUTUBE_API_KEY_{1-12}` | YouTube Data API keys | Required |
| `HF_TOKEN` | HuggingFace API token | Optional |
| `REDIS_HOST` | Redis server host | `localhost` |
| `MAX_FETCH_RESULTS` | Max results per source | `10` |
| `DEFAULT_LANGUAGE` | Default content language | `en` |
| `SOCKET_WAIT_TIMEOUT` | Frontend socket timeout | `30` |

## Related Repositories

Bosla is a multi-repository project:

| Repository | Description |
|------------|-------------|
| [API](https://github.com/Bosla-Ai/API) | .NET backend service |
| **BoslaPipeline** | This repository |
| [bosla-ai-frontend](https://github.com/Bosla-Ai/bosla-ai-frontend) | React frontend |

## Contributing

We welcome contributions! Please read our [Contributing Guide](CONTRIBUTING.md) for details on:

* Development setup
* Coding standards
* Testing guidelines
* Pull request process

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Notes

* **Python 3.11 required**: `undetected-chromedriver` is incompatible with Python 3.12+
* **Xvfb required**: For headless browser operation on Linux servers
* **Redis recommended**: Significantly reduces API quota usage through caching
