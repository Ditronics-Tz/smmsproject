# ============================================================================
# Multi-Stage Dockerfile for Django SMMS Project
# Optimized for minimal image size (<200MB), security, and production use
# ============================================================================

# ============================================================================
# Stage 1: Builder - Install dependencies and build packages
# ============================================================================
FROM python:3.12-slim-bookworm AS builder

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies required for building Python packages
# WeasyPrint requires: pango, cairo, gdk-pixbuf, libffi, glib
# PostgreSQL requires: libpq-dev
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    build-essential \
    libpq-dev \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libffi-dev \
    libcairo2 \
    libglib2.0-0 \
    shared-mime-info \
    && rm -rf /var/lib/apt/lists/*

# Create virtual environment
RUN python -m venv /opt/venv

# Activate virtual environment
ENV PATH="/opt/venv/bin:$PATH"

# Copy requirements and install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --upgrade pip setuptools wheel && \
    pip install -r /tmp/requirements.txt && \
    pip install gunicorn whitenoise

# ============================================================================
# Stage 2: Runtime - Minimal production image
# ============================================================================
FROM python:3.12-slim-bookworm AS runtime

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=smmsproject.settings \
    PATH="/opt/venv/bin:$PATH"

# Install only runtime dependencies (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf2.0-0 \
    libcairo2 \
    libglib2.0-0 \
    netcat-traditional \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user for security
RUN groupadd -r django --gid=1000 && \
    useradd -r -g django --uid=1000 --home-dir=/app --shell=/bin/bash django

# Create app directory
WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /opt/venv /opt/venv

# Copy application code
COPY --chown=django:django . /app/

# Copy entrypoint script
COPY --chown=django:django entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Create directories for static and media files
RUN mkdir -p /app/static /app/uploads && \
    chown -R django:django /app/static /app/uploads

# Switch to non-root user
USER django

# Expose port 8000
EXPOSE 8000

# Set entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]

# Default command (can be overridden in docker-compose)
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]