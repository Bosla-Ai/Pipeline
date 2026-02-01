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

[![Python](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Overview

**BoslaPipeline** is a **modular Python pipeline** designed to fetch, process, and classify learning resources from various sources.
It integrates with **SQL Server** for storing results and supports **easy extension** with new data sources or custom classification models.

---

## Features

* Fetch data from multiple sources: **YouTube, Udemy, Coursera**, etc.
* Optional **web scraping** for sources without APIs
* **Clean and normalize** text data
* **Classify resources** by level: Beginner, Intermediate, Advanced or custom tags
* Store results in **SQL Server**
* Integrate **pretrained models** or **fine-tuned HuggingFace models**

---

## Repository Structure

```
BoslaPipeline/
│── README.md
│── requirements.txt
│── .env
│
├── src/
│   ├── main.py            # Entry point of the pipeline
│   ├── config/settings.py # Configuration & secrets
│   ├── fetchers/          # External APIs or scraping
│   ├── processors/        # Data cleaning & classification
│   ├── storage/           # Database operations
│   └── utils/             # Logging & helper functions
│
└── tests/                 # Unit tests
```

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/Bosla-Ai/BoslaPipeline.git
cd BoslaPipeline
```

### 2. Install Xvfb for headless browsing

```bash
# Ubuntu
sudo apt update && sudo apt upgrade
sudo apt install xvfb

# Fedora
sudo dnf update
sudo dnf install xorg-x11-server-Xvfb
```

### 3. Create a Python 3.11 virtual environment (Recommended)

**Note:** This project requires Python 3.11 due to dependencies (undetected-chromedriver) that are incompatible with Python 3.12+.

# Ubuntu: Ensure Python 3.11 is installed first

```bash
# ubuntu
sudo apt install python3.11 python3.11-venv

# fedora
sudo dnf install python3.11 python3.11-venv
```

# Create the virtual environment

```bash
python3.11 -m venv venv
```

# Activate

```bash
source venv/bin/activate
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Set up `.env`

Create a `.env` file with necessary API keys and database connection string. Example:

```
YOUTUBE_API_KEY=your_key_here
UDEMY_CLIENT_ID=your_client_id
UDEMY_CLIENT_SECRET=your_client_secret
DB_CONNECTION_STRING=mssql+pyodbc://user:pass@server/db?driver=ODBC+Driver+17+for+SQL+Server
MAX_FETCH_RESULTS=10
DEFAULT_LANGUAGE=en
```

---

## Usage

Run the main pipeline:

```bash
python3.11 -m src.main
```

---

## Configuration

* All sensitive data and configurable parameters are in `src/config/settings.py` and loaded from `.env`.
* Modify settings for API keys, DB connections, or fetch limits.

---

## Extending the Pipeline

* **Add new fetchers** → `src/fetchers/`
* **Update classification logic** or replace the model → `src/processors/classifier.py`
* **Modify storage logic** → `src/storage/db.py`

---

## Testing

Unit tests are in the `tests/` directory:

```bash
pytest tests/
```

---

## Notes

* Recommended Python version: **3.11**
* Ensure **Xvfb** is installed for headless browser operation.
* Compatible with **SQL Server** (via `pyodbc`) and **HuggingFace models**.
