# Build stage
FROM python:3.12-slim AS builder

WORKDIR /app

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------------
# Production stage
FROM python:3.12-slim AS production

WORKDIR /app

# Runtime system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY . .

# Create non-root user
RUN useradd -m -u 1000 deskmate \
    && chown -R deskmate:deskmate /app

USER deskmate

# Data directories
RUN mkdir -p /app/mock_data /app/data

# Environment defaults (override via docker-compose or Kubernetes secrets)
ENV DATABASE_URL="sqlite:////app/data/deskmate.db" \
    HOST="0.0.0.0" \
    PORT="8000" \
    WORKERS="2" \
    LOG_LEVEL="info" \
    PYTHONPATH="/app" \
    PYTHONUNBUFFERED="1"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

EXPOSE 8000

# Startup: init DB + seed + serve
CMD ["sh", "-c", "python -c 'from db.base import init_db; from db.seed import seed_demo_data; from db.base import session_scope; init_db(); [seed_demo_data(s) for s in [__import__(\"contextlib\").suppress()]]' 2>/dev/null; uvicorn backend.main:app --host $HOST --port $PORT --workers $WORKERS --log-level $LOG_LEVEL"]
