# Contributing to BoslaPipeline

Thank you for your interest in contributing to BoslaPipeline. This document outlines the guidelines and standards for contributing to this project. We appreciate your efforts to improve the code quality and functionality.

## Code of Conduct

All contributors are expected to maintain a professional and respectful environment. Harassment, discrimination, or offensive language will not be tolerated. Please focus on constructive technical discussion and collaboration.

## Development Setup

To set up your development environment, please follow the platform-specific instructions below.

### Linux (Ubuntu/Debian)

1. **Install Prerequisites**:
   ```bash
   sudo apt update && sudo apt upgrade
   sudo apt install python3.11 python3.11-venv xvfb redis-server google-chrome-stable
   ```

2. **Start Redis**:
   ```bash
   sudo systemctl start redis-server
   # or: redis-server --daemonize yes
   ```

3. **Clone & Configure**:
   ```bash
   git clone https://github.com/Bosla-Ai/BoslaPipeline.git
   cd BoslaPipeline
   cp .env.example .env
   ```
   Update `.env` with your API keys.

4. **Create Virtual Environment**:
   ```bash
   python3.11 -m venv venv
   source venv/bin/activate
   ```

5. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

6. **Run the Application**:
   ```bash
   python -m src.main
   ```

### Linux (Fedora)

1. **Install Prerequisites**:
   ```bash
   sudo dnf update
   sudo dnf install python3.11 python3.11-venv xorg-x11-server-Xvfb redis
   ```

2. **Start Redis**:
   ```bash
   sudo systemctl start redis
   ```

3. Follow steps 3-6 from Ubuntu instructions above.

### macOS

1. **Install Prerequisites**:
   ```bash
   brew install python@3.11 redis
   brew install --cask google-chrome
   ```

2. **Start Redis**:
   ```bash
   brew services start redis
   ```

3. **Clone & Configure**:
   ```bash
   git clone https://github.com/Bosla-Ai/BoslaPipeline.git
   cd BoslaPipeline
   cp .env.example .env
   ```
   Update `.env` with your API keys.

4. **Create Virtual Environment**:
   ```bash
   python3.11 -m venv venv
   source venv/bin/activate
   ```

5. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

6. **Run the Application**:
   ```bash
   python -m src.main
   ```

### Windows

1. **Install Prerequisites**:
   * [Python 3.11](https://www.python.org/downloads/) (check "Add to PATH")
   * [Redis for Windows](https://github.com/microsoftarchive/redis/releases) or use WSL2
   * [Google Chrome](https://www.google.com/chrome/)

2. **Start Redis**:
   ```powershell
   # If using Redis for Windows
   redis-server
   ```

3. **Clone & Configure**:
   ```powershell
   git clone https://github.com/Bosla-Ai/BoslaPipeline.git
   cd BoslaPipeline
   copy .env.example .env
   ```
   Update `.env` with your API keys.

4. **Create Virtual Environment**:
   ```powershell
   python -m venv venv
   venv\Scripts\activate
   ```

5. **Install Dependencies**:
   ```powershell
   pip install -r requirements.txt
   ```

6. **Run the Application**:
   ```powershell
   python -m src.main
   ```

### Docker

For containerized development:

```bash
docker build -t bosla-pipeline .
docker run -p 7860:7860 --env-file .env bosla-pipeline
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `YOUTUBE_API_KEY_{1-12}` | Yes (at least 1) | YouTube Data API keys |
| `HF_TOKEN` | No | HuggingFace API token |
| `UDEMY_CLIENT_ID` | No | Udemy affiliate client ID |
| `UDEMY_CLIENT_SECRET` | No | Udemy affiliate client secret |
| `REDIS_HOST` | No | Redis server host (default: localhost) |
| `MAX_FETCH_RESULTS` | No | Max results per query (default: 10) |
| `DEFAULT_LANGUAGE` | No | Content language (default: en) |

## Coding Standards

We adhere to strict coding standards to ensure consistency and maintainability.

### General Guidelines

* **Python 3.11**: Use Python 3.11 features but avoid 3.12+ syntax
* **Type Hints**: Use type hints for function parameters and return values
* **Docstrings**: Write docstrings for all public functions and classes
* **Single Responsibility**: Functions should do one thing well
* **DRY Principle**: Avoid code duplication

### Code Formatting

The project uses **Black** for code formatting:

```bash
# Format all files
black src/ tests/

# Check formatting without changes
black --check src/ tests/
```

**Black Configuration** (in `pyproject.toml` or command line):
* Line length: 88 characters
* Target version: Python 3.11

### Naming Conventions

| Type | Convention | Example |
|------|------------|---------|
| Functions | snake_case | `fetch_youtube_data()` |
| Variables | snake_case | `video_count` |
| Constants | SCREAMING_SNAKE_CASE | `MAX_RETRIES` |
| Classes | PascalCase | `KeyManager` |
| Modules | snake_case | `youtube_fetcher.py` |

### Import Order

Organize imports in this order (PEP 8):

```python
# 1. Standard library
import os
import json
from datetime import datetime

# 2. Third-party packages
import aiohttp
from fastapi import FastAPI
from pydantic import BaseModel

# 3. Local imports
from src.config.settings import YOUTUBE_API_KEYS
from src.utils.cache import cache
```

### Async/Await Best Practices

* Use `async def` for I/O-bound operations
* Prefer `asyncio.gather()` for concurrent operations
* Use `aiohttp` for HTTP requests, not `requests`
* Handle exceptions with specific error types

```python
# Good
async def fetch_data(urls: list[str]) -> list[dict]:
    async with aiohttp.ClientSession() as session:
        tasks = [fetch_single(session, url) for url in urls]
        return await asyncio.gather(*tasks, return_exceptions=True)

# Bad
def fetch_data(urls: list[str]) -> list[dict]:
    return [requests.get(url).json() for url in urls]
```

### Error Handling

* Use specific exception types
* Log errors with context
* Provide fallback behavior where appropriate

```python
try:
    data = await fetch_youtube_data(session, url, params)
except aiohttp.ClientError as e:
    logger.error(f"Network error fetching {url}: {e}")
    return {}
except json.JSONDecodeError as e:
    logger.error(f"Invalid JSON response from {url}: {e}")
    return {}
```

## Project Structure

### Adding a New Fetcher

1. Create a new file in `src/fetchers/videos/`:
   ```python
   # src/fetchers/videos/new_source_fetcher.py
   
   import aiohttp
   from src.utils.cache import cache, generate_cache_key
   
   async def fetch_new_source(tags: list[str], language: str = "en") -> dict:
       """
       Fetch content from NewSource API.
       
       Args:
           tags: List of topics to search
           language: Content language (en/ar)
       
       Returns:
           Dictionary mapping tags to resources
       """
       results = {}
       async with aiohttp.ClientSession() as session:
           for tag in tags:
               cache_key = generate_cache_key("newsource", tag, language)
               cached = await cache.get(cache_key)
               if cached:
                   results[tag] = cached
                   continue
               
               # Fetch and process data
               data = await _fetch_tag(session, tag, language)
               if data:
                   await cache.set(cache_key, data)
                   results[tag] = data
       
       return results
   ```

2. Register in `src/api.py` if needed.

### Adding a New Utility

Place shared utilities in `src/utils/`:

```python
# src/utils/my_utility.py

def process_data(data: dict) -> dict:
    """
    Process raw data into normalized format.
    
    Args:
        data: Raw data dictionary
    
    Returns:
        Normalized data dictionary
    """
    # Implementation
    pass
```

## Testing

### Running Tests

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/test_youtube_fetcher.py

# Run with coverage
pytest tests/ --cov=src --cov-report=html

# Run in parallel
pytest tests/ -n auto

# Run with verbose output
pytest tests/ -v
```

### Writing Tests

* Place tests in `tests/` directory
* Name test files `test_*.py`
* Use pytest fixtures for common setup
* Mock external API calls

```python
# tests/test_youtube_fetcher.py

import pytest
from unittest.mock import AsyncMock, patch
from src.fetchers.videos.youtube_fetcher import fetch_youtube_data

@pytest.fixture
def mock_session():
    """Create a mock aiohttp session."""
    session = AsyncMock()
    return session

@pytest.mark.asyncio
async def test_fetch_youtube_data_success(mock_session):
    """Test successful YouTube data fetch."""
    mock_response = AsyncMock()
    mock_response.status = 200
    mock_response.json.return_value = {"items": [{"id": "test123"}]}
    mock_session.get.return_value.__aenter__.return_value = mock_response
    
    result = await fetch_youtube_data(mock_session, "https://api.example.com", {})
    
    assert "items" in result
    assert len(result["items"]) == 1

@pytest.mark.asyncio
async def test_fetch_youtube_data_quota_exceeded(mock_session):
    """Test handling of quota exceeded error."""
    mock_response = AsyncMock()
    mock_response.status = 403
    mock_response.text.return_value = "quota exceeded"
    mock_session.get.return_value.__aenter__.return_value = mock_response
    
    result = await fetch_youtube_data(mock_session, "https://api.example.com", {})
    
    assert result == {}
```

### Test Categories

| Category | Description | Example |
|----------|-------------|---------|
| Unit Tests | Test individual functions | `test_scoring.py` |
| Integration Tests | Test component interaction | `test_api.py` |
| API Tests | Test HTTP endpoints | `test_api_sources.py` |
| Socket Tests | Test real-time communication | `test_socket_server.py` |

## Pull Request Process

1. **Find an Issue**: Ensure there is an open issue for the task you want to work on. If not, open one first.

2. **Get Assigned**: Do not open a Pull Request unless the issue has been assigned to you.

3. **Create a Branch**: Create a new branch from `main` with a descriptive name:
   ```bash
   git checkout -b feature/add-coursera-caching
   git checkout -b fix/youtube-quota-handling
   ```

4. **Implement Changes**: Make your changes following the coding standards.

5. **Format Code**:
   ```bash
   black src/ tests/
   ```

6. **Run Tests**:
   ```bash
   pytest tests/
   ```

7. **Commit Changes**: Write clear, descriptive commit messages:
   ```
   feat: add Redis caching for Coursera results
   fix: handle YouTube 403 quota errors with key rotation
   docs: update API documentation in README
   test: add unit tests for scoring module
   ```

8. **Push & Create PR**:
   ```bash
   git push -u origin feature/your-branch-name
   ```
   Then open a Pull Request against the `main` branch.

9. **PR Description**:
   * Reference the issue (e.g., `Closes #123`)
   * Describe the changes and approach
   * Note any breaking changes or migration steps

10. **Code Review**: Address feedback from reviewers promptly.

## Issue Reporting

### Bug Reports

When reporting a bug, include:

* **Description**: Clear description of the problem
* **Steps to Reproduce**: Exact steps to reproduce the issue
* **Expected Behavior**: What should happen
* **Actual Behavior**: What actually happens
* **Environment**: Python version, OS, dependencies
* **Logs**: Relevant error logs or stack traces

### Feature Requests

When requesting a feature, describe:

* **Use Case**: Why is this feature needed?
* **Proposed Solution**: How should it work?
* **API Design**: If applicable, proposed endpoint or function signature
* **Alternatives Considered**: Other approaches you've thought of

## Related Repositories

Bosla is a multi-repository project. When contributing, be aware of:

| Repository | Description | Contributing Guide |
|------------|-------------|-------------------|
| [API](https://github.com/Bosla-Ai/API) | .NET backend service | [CONTRIBUTING.md](https://github.com/Bosla-Ai/API/blob/main/CONTRIBUTING.md) |
| **BoslaPipeline** | This repository | You are here |
| [bosla-ai-frontend](https://github.com/Bosla-Ai/bosla-ai-frontend) | React frontend | [CONTRIBUTING.md](https://github.com/Bosla-Ai/bosla-ai-frontend/blob/main/CONTRIBUTING.md) |

Cross-repository changes may require coordinated PRs.

---

Thank you for contributing to BoslaPipeline!
