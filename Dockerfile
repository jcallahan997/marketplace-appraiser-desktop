# =============================================================================
# Stage 1: Build the React/Vite dashboard
# =============================================================================
FROM node:20-alpine AS dashboard-builder

WORKDIR /build

COPY dashboard/package.json ./
RUN npm install

COPY dashboard/ ./
RUN npm run build


# =============================================================================
# Stage 2: Python runtime (FastAPI + dashboard static files)
# =============================================================================
FROM python:3.11-slim AS runtime

# System dependencies required by Playwright CDP client and general operation
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl wget gnupg ca-certificates \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libdbus-1-3 libxkbcommon0 \
    libatspi2.0-0 libxcomposite1 libxdamage1 libxfixes3 \
    libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
    fonts-liberation fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies (editable install preserves Path(__file__) resolution)
COPY pyproject.toml ./
COPY src/ ./src/
RUN pip install --no-cache-dir -e ".[server]"

# Copy helper scripts
COPY scripts/ ./scripts/

# Copy built dashboard from stage 1
COPY --from=dashboard-builder /build/dist ./dashboard/dist

# Create output directories (will be overridden by bind mount)
RUN mkdir -p /app/output/history /app/output/images /app/output/feedback

# Default environment for Docker Compose networking
ENV CHROME_CDP_URL=http://chrome:9222
ENV LANGFUSE_HOST=http://langfuse:3000

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl --fail http://localhost:8000/api/health || exit 1

CMD ["uvicorn", "marketplace_appraiser.server:app", "--host", "0.0.0.0", "--port", "8000"]
