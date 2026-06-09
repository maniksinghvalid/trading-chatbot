# backend/Dockerfile — multi-stage uv build for the FastAPI backend
#
# Stage 1 (builder): install dependencies with uv into /app/.venv
# Stage 2 (runtime): copy venv + src, run uvicorn
#
# Secrets are injected at runtime via environment variables — never hardcoded here.
# Build with:  docker build -t chatbot-backend .  (from trading-chatbot/backend/)

# ---- builder stage -------------------------------------------------------
FROM ghcr.io/astral-sh/uv:0.6-python3.12-bookworm-slim AS builder

WORKDIR /app

# Copy dependency files first for layer-cache efficiency
COPY pyproject.toml uv.lock ./

# Install dependencies into a project-local venv (no editable install of src yet)
RUN uv sync --frozen --no-install-project

# Copy source and install the project itself
COPY src/ ./src/
RUN uv sync --frozen

# ---- runtime stage -------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime

WORKDIR /app

# Copy the venv from builder (keeps runtime image slim — no uv, no build tools)
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src

# Activate the venv for all subsequent commands
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
# Python won't write .pyc files to disk inside the container
ENV PYTHONDONTWRITEBYTECODE=1

# Non-root user for security
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser
USER appuser

# PORT is overridable by Fly.io / Railway / other platforms
ENV PORT=8000

EXPOSE ${PORT}

# Entry point: uvicorn src.main:app
# --host 0.0.0.0 so the container port is reachable from outside
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
