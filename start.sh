#!/usr/bin/env bash
set -euo pipefail

# 1. Clean up any leftover lock files for Xvfb to prevent lock issues on reboot/container restart
echo "[start] Cleaning up stale locks..."
rm -f /tmp/.X99-lock || true
mkdir -p /tmp/.X11-unix || true
chmod 1777 /tmp/.X11-unix 2>/dev/null || true

# 2. Start Redis in daemonized mode with safe maxmemory constraints inside a single container environment.
# Setting a conservative limit like 1024mb (or configurable via REDIS_MAXMEMORY) and volatile-ttl maxmemory policy prevents container OOM.
REDIS_MAXMEM="${REDIS_MAXMEMORY:-1024mb}"
REDIS_MEM_POLICY="${REDIS_MAXMEMORY_POLICY:-volatile-ttl}"

echo "[start] Starting Redis server (maxmemory: ${REDIS_MAXMEM}, policy: ${REDIS_MEM_POLICY})..."
redis-server --daemonize yes \
             --dir "${REDIS_DATA_DIR:-/home/user/redis-data}" \
             --bind 127.0.0.1 \
             --port 6379 \
             --maxmemory "$REDIS_MAXMEM" \
             --maxmemory-policy "$REDIS_MEM_POLICY"

# 3. Wait for Redis to be fully ready by polling redis-cli ping
echo "[start] Waiting for Redis to become available..."
redis_ready=false
for i in {1..30}; do
  if redis-cli ping | grep -q PONG; then
    echo "[start] Redis is ready and accepting connections."
    redis_ready=true
    break
  fi
  sleep 0.5
done

if [ "$redis_ready" = false ]; then
  echo "[start] ERROR: Redis failed to start or respond within timeout." >&2
  exit 1
fi

# 4. Start Xvfb (Virtual Framebuffer) in the background for Selenium Chrome instances
echo "[start] Starting Xvfb on display :99..."
Xvfb :99 -screen 0 1920x1080x24 -ac &
XVFB_PID=$!
export DISPLAY=:99

# 5. Wait for Xvfb to be fully initialized using xdpyinfo
echo "[start] Waiting for Xvfb to become ready..."
xvfb_ready=false
for i in {1..30}; do
  if xdpyinfo -display :99 >/dev/null 2>&1; then
    echo "[start] Xvfb is ready on display :99."
    xvfb_ready=true
    break
  fi
  sleep 0.5
done

if [ "$xvfb_ready" = false ]; then
  echo "[start] ERROR: Xvfb failed to start within timeout." >&2
  kill -0 $XVFB_PID 2>/dev/null && kill $XVFB_PID
  exit 1
fi

# 6. Start the web application using exec to replace the shell process, ensuring proper PID 1 signal propagation
echo "[start] Launching ASGI App via Uvicorn..."
exec uvicorn src.main:combined_app --host 0.0.0.0 --port "${PORT:-7860}"
