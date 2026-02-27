# syntax=docker/dockerfile:1.4

# Build stage
FROM python:3.13-slim-bookworm AS builder

# Build arguments for versioning
ARG VERSION=1.0.0
ARG BUILD_DATE
ARG VCS_REF
ARG VCS_URL=https://github.com/menottim/splintarr

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libffi-dev \
    libssl-dev \
    libsqlcipher-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Install Poetry
RUN pip install --no-cache-dir poetry==2.3.2

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Install dependencies
RUN poetry config virtualenvs.create false && \
    poetry install --only main --no-interaction --no-ansi --no-root

# Runtime stage
FROM python:3.13-slim-bookworm

# Metadata labels
LABEL org.opencontainers.image.title="Splintarr" \
      org.opencontainers.image.description="Intelligent backlog search automation for Sonarr and Radarr" \
      org.opencontainers.image.version="${VERSION}" \
      org.opencontainers.image.created="${BUILD_DATE}" \
      org.opencontainers.image.source="${VCS_URL}" \
      org.opencontainers.image.revision="${VCS_REF}" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.vendor="Splintarr" \
      maintainer="splintarr@example.com"

# Security: Create non-root user
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -s /sbin/nologin -c "Application user" appuser

# Install runtime dependencies including gosu for privilege dropping
RUN apt-get update && apt-get install -y --no-install-recommends \
    libssl3 \
    libsqlcipher0 \
    ca-certificates \
    gosu \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

WORKDIR /app

# Set Python path so splintarr module is importable
ENV PYTHONPATH=/app/src

# Copy Python packages from builder
COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code
COPY --chown=appuser:appuser src/ ./src/
COPY --chown=appuser:appuser alembic/ ./alembic/
COPY --chown=appuser:appuser alembic.ini ./

# Create data directory
RUN mkdir -p /data && chown appuser:appuser /data

# Copy and set up entrypoint script
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

# Note: Container starts as root, entrypoint script will drop to appuser
# This allows fixing /data permissions on Windows before switching users
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]

# Health check with better error handling
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import httpx, sys; \
        try: \
            resp = httpx.get('http://localhost:7337/health', timeout=5.0); \
            sys.exit(0 if resp.status_code == 200 else 1); \
        except: \
            sys.exit(1)" || exit 1

# Expose port
EXPOSE 7337

# Run application
CMD ["uvicorn", "src.splintarr.main:app", "--host", "0.0.0.0", "--port", "7337"]
