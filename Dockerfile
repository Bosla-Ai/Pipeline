# Use Python 3.11-slim-bullseye for stability with ODBC 17 and Chrome
FROM python:3.11-slim-bullseye

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive


# Install system dependencies (Run as Root)
# FIX: Added 'xauth' here to solve the xvfb error
# Added 'redis-server' for caching in HF Spaces (single container)
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg2 curl ca-certificates apt-transport-https software-properties-common \
    xauth unzip libgconf-2-4 libnss3 libxss1 libasound2 fonts-liberation \
    libgbm1 libu2f-udev xdg-utils redis-server xvfb x11-utils \
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

# Create a new user (User ID 1000) because Root is forbidden
RUN useradd -m -u 1000 user

# Switch to this user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# Set working directory to the user's home folder
WORKDIR $HOME/app

# Copy files with PERMISSION for the new user (--chown=user)
COPY --chown=user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright system deps as root (requires apt-get), then switch back
USER root
RUN pip install --no-cache-dir playwright && python3 -m playwright install-deps chromium
USER user

# Install Scrapling browser binaries + Playwright browsers as user
RUN scrapling install || true
RUN playwright install chromium
COPY --chown=user . .

# Create Redis data directory for non-root user
RUN mkdir -p $HOME/redis-data

# Make sure start.sh is executable
RUN chmod +x start.sh

# Change Port to 7860 (Hugging Face Requirement)
EXPOSE 7860

# Add healthcheck to monitor application health status
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:7860/health')" || exit 1

# Start command: Execute start.sh which safely orchestrates Redis, Xvfb, and Uvicorn
CMD ["./start.sh"]