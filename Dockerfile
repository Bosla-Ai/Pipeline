# Use Python 3.11-slim-bullseye for stability with ODBC 17 and Chrome
FROM python:3.11-slim-bullseye

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# Install system dependencies (Run as Root)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg2 curl ca-certificates apt-transport-https software-properties-common \
    xvfb xauth unzip libgconf-2-4 libnss3 libxss1 libasound2 fonts-liberation \
    libgbm1 libu2f-udev xdg-utils redis-server \
    && rm -rf /var/lib/apt/lists/*

# Install Google Chrome (Run as Root)
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add - \
    && echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update \
    && apt-get install -y google-chrome-stable \
    && rm -rf /var/lib/apt/lists/*

# Install Microsoft ODBC 17 (Run as Root)
RUN curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - \
    && curl https://packages.microsoft.com/config/debian/11/prod.list > /etc/apt/sources.list.d/mssql-release.list \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y msodbcsql17 unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

# Create Xvfb socket directory before switching users
RUN mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix

# --- FIX: Install Python packages and Playwright OS dependencies as ROOT ---
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install-deps

# Create a new user (User ID 1000)
RUN useradd -m -u 1000 user

# Switch to this user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# Set working directory to the user's home folder
WORKDIR $HOME/app

# Install only the browser binaries and scrapling as USER ---
RUN playwright install chromium
RUN scrapling install

# Copy remaining files
COPY --chown=user . .

# Create Redis data directory for non-root user
RUN mkdir -p $HOME/redis-data

# Change Port to 7860 (Hugging Face Requirement)
EXPOSE 7860

# Start command
CMD ["sh", "-c", "redis-server --daemonize yes --dir /home/user/redis-data --bind 127.0.0.1 --port 6379 && Xvfb :99 -screen 0 1920x1080x24 & sleep 2 && export DISPLAY=:99 && uvicorn src.main:combined_app --host 0.0.0.0 --port 7860"]