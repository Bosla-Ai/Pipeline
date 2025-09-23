# BoslaPipeline

## Overview

BoslaPipeline is a modular Python pipeline designed to fetch, process, and classify learning resources from various external sources. It integrates with SQL Server for storing results and can be easily extended with additional data sources or classification models.

## Features

* Fetch data from multiple sources (YouTube, Udemy, Coursera, etc.)
* Optional web scraping for sources without an API
* Clean and normalize text data
* Classify resources by level (Beginner, Intermediate, Advanced) or custom tags
* Store results in SQL Server
* Flexible integration of pretrained models or fine-tuned HuggingFace models

## Repository Structure

```
BoslaPipeline/
│── README.md
│── requirements.txt
│── .env
│
├── src/
│   ├── main.py            # Entry point of the pipeline
│   ├── config/settings.py # Configuration and secrets
│   ├── fetchers/          # External APIs or scraping
│   ├── processors/        # Data cleaning and classification
│   ├── storage/           # Database operations
│   └── utils/             # Logging and helper functions
│
└── tests/                 # Unit tests
```

## Installation

1. Clone the repository:

```bash
git clone https://github.com/Bosla-Ai/BoslaPipeline.git
cd BoslaPipeline
```

2. Create a virtual environment and activate it:

```bash
python -m venv venv
# On Linux/macOS
source venv/bin/activate
# On Windows
venv\Scripts\activate
```

3. Install dependencies:

```bash
pip install -r requirements.txt
```

4. Set up `.env` file with necessary API keys and database connection string.

## Usage

Run the main pipeline:

```bash
python src/main.py
```

## Configuration

* All sensitive data and configurable parameters are stored in `src/config/settings.py` and loaded from `.env`.
* Example `.env`:

```
YOUTUBE_API_KEY=your_key_here
UDEMY_CLIENT_ID=your_client_id
UDEMY_CLIENT_SECRET=your_client_secret
DB_CONNECTION_STRING=mssql+pyodbc://user:pass@server/db?driver=ODBC+Driver+17+for+SQL+Server
MAX_FETCH_RESULTS=10
DEFAULT_LANGUAGE=en
```

## Extending the Pipeline

* Add new fetchers in `src/fetchers/`.
* Update classification logic or replace model in `src/processors/classifier.py`.
* Add new database tables or modify storage logic in `src/storage/db.py`.

## Testing

* Unit tests are located in the `tests/` directory.
* Run tests with:

```bash
pytest tests/
```