FROM python:3.12-slim AS backend-runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app
COPY requirements-runtime.txt .
RUN apt-get update && \
    apt-get install --yes --no-install-recommends libgomp1 && \
    rm -rf /var/lib/apt/lists/* && \
    python -m pip install \
    --no-deps \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    --requirement requirements-runtime.txt

COPY alembic.ini pyproject.toml ./
COPY backend ./backend
COPY config ./config
COPY data ./data
COPY artifacts ./artifacts
COPY ml ./ml
COPY reports ./reports
COPY scripts ./scripts
RUN python -m scripts.download_rag_models

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM node:22-bookworm-slim AS frontend-dependencies
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

FROM frontend-dependencies AS frontend-build
ARG NEXT_PUBLIC_AUTH_ENABLED=false
ENV NEXT_PUBLIC_AUTH_ENABLED=$NEXT_PUBLIC_AUTH_ENABLED \
    NEXT_TELEMETRY_DISABLED=1
COPY frontend/ ./
RUN npm run build

FROM node:22-bookworm-slim AS frontend-runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1
WORKDIR /app/frontend
COPY --from=frontend-build /app/frontend/.next/standalone ./
COPY --from=frontend-build /app/frontend/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
