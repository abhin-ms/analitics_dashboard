# One image for the whole app: the React build is served by the FastAPI
# backend itself (app/main.py serves ../frontend/dist), so the API, the SPA
# and the Socket.IO live updates all share one origin behind the server's nginx.

# ── 1. Build the frontend ─────────────────────────────────────────────
FROM node:22-alpine AS web
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# ── 2. Backend runtime ────────────────────────────────────────────────
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app/backend

COPY backend/requirements.txt .
RUN pip install -r requirements.txt

COPY backend/ .
# main.py looks for the build at <repo>/frontend/dist
COPY --from=web /src/frontend/dist /app/frontend/dist

RUN useradd --system --uid 1000 --home /app app \
    && mkdir -p /app/backend/logs \
    && chown -R app /app/backend/logs
USER app

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# --proxy-headers: take the visitor's IP from nginx's X-Forwarded-For, so
# the login rate limiter sees real IPs instead of the proxy's for everyone.
# The container port is only published on the server's 127.0.0.1.
CMD ["uvicorn", "app.main:socket_app", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
